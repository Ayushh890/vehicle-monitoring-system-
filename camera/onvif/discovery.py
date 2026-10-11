"""ONVIF camera discovery module.

Allows operator to scan local network, discover compatible cameras,
and display camera information including IP, manufacturer, model,
and RTSP endpoint when available.

Usage:
    from backend.camera.onvif.discover import discover_onvif_cameras
    cameras = discover_onvif_cameras(timeout=5)
    for cam in cameras:
        print(f"{cam['ip']}: {cam['manufacturer']} {cam['model']}")
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# ONVIF discovery probe message (WS-Discovery)
_ONVIF_DISCOVERY_MSG = '''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap/envelope/">
  <s:Header>
    <wsa:Action xmlns:wsa="http://www.w3.org/2005/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/enumerate</wsa:Action>
    <wsa:To xmlns:wsa="http://www.w3.org/2005/08/addressing">urn:schemas-upnp-org:service:MediaRenderer:1</wsa:To>
  </s:Header>
  <s:Body/>
</s:Envelope>'''


class OnvifCameraInfo:
    """Information about a discovered ONVIF camera."""
    
    def __init__(
        self,
        ip: str,
        mac: Optional[str] = None,
        manufacturer: Optional[str] = None,
        model: Optional[str] = None,
        firmware: Optional[str] = None,
        rtsp_url: Optional[str] = None,
        network_interface: Optional[str] = None,
    ) -> None:
        self.ip = ip
        self.mac = mac
        self.manufacturer = manufacturer
        self.model = model
        self.firmware = firmware
        self.rtsp_url = rtsp_url
        self.network_interface = network_interface
    
    @property
    def is_configured(self) -> bool:
        """Check if camera has RTSP endpoint available."""
        return self.rtsp_url is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "ip": self.ip,
            "mac": self.mac,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "firmware": self.firmware,
            "rtsp_url": self.rtsp_url,
            "network_interface": self.network_interface,
        }
    
    def __repr__(self) -> str:
        return f"<OnvifCameraInfo ip={self.ip} manufacturer={self.manufacturer} model={self.model}>"


async def discover_onvif_cameras(
    timeout: float = 5.0,
    network_interface: Optional[str] = None,
) -> List[OnvifCameraInfo]:
    """Discover ONVIF cameras on the local network using WS-Discovery.
    
    Args:
        timeout: Discovery timeout in seconds.
        network_interface: Specific network interface to query (None = all).
    
    Returns:
        List of OnvifCameraInfo objects for discovered cameras.
    
    Note:
        ONVIF discovery uses WS-Discovery multicast. This may not work
        in all network environments (e.g., Docker containers without
        host network access, networks with blocked multicast).
    """
    discovered: List[OnvifCameraInfo] = []
    
    try:
        # Create UDP socket for WS-Discovery
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Join multicast group if on a network that supports it
        multicast_group = "239.255.255.250"
        multicast_port = 1900
        
        if network_interface:
            try:
                sock.bind((network_interface, 0))
            except OSError:
                logger.warning(f"Could not bind to interface {network_interface}, using default")
        
        # Send discovery probe
        probe = _ONVIF_DISCOVERY_MSG.encode("utf-8")
        sock.sendto(probe, (multicast_group, multicast_port))
        
        # Listen for responses
        responses: Dict[str, OnvifCameraInfo] = {}
        
        try:
            while True:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                
                # Parse ONVIF response
                camera_info = _parse_onvif_response(data, ip)
                if camera_info:
                    if ip not in responses:
                        responses[ip] = camera_info
                    else:
                        # Merge with existing info
                        existing = responses[ip]
                        if camera_info.manufacturer and not existing.manufacturer:
                            existing.manufacturer = camera_info.manufacturer
                        if camera_info.model and not existing.model:
                            existing.model = camera_info.model
                        if camera_info.rtsp_url and not existing.rtsp_url:
                            existing.rtsp_url = camera_info.rtsp_url
        except socket.timeout:
            pass
        
        discovered = list(responses.values())
        logger.info(f"Discovered {len(discovered)} ONVIF cameras")
        
    except ImportError:
        logger.warning("ONVIF discovery requires socket module")
    except Exception as e:
        logger.error(f"ONVIF discovery error: {e}")
    
    return discovered


def _parse_onvif_response(data: bytes, ip: str) -> Optional[OnvifCameraInfo]:
    """Parse ONVIF WS-Discovery response from raw bytes."""
    try:
        text = data.decode("utf-8", errors="ignore")
        
        # Extract key information from the response
        manufacturer = _extract_xml_field(text, "dn:Manufacturer")
        model = _extract_xml_field(text, "dn:Model")
        firmware = _extract_xml_field(text, "dn:FirmwareVersion")
        nt = _extract_xml_field(text, "dn:NT")
        
        # Only process if this is a camera service announcement
        if nt and "Camera" in nt:
            rtsp_url = _extract_rtsp_url(text)
            
            camera_info = OnvifCameraInfo(
                ip=ip,
                manufacturer=manufacturer,
                model=model,
                firmware=firmware,
                rtsp_url=rtsp_url,
            )
            return camera_info
    except Exception as e:
        logger.debug(f"Failed to parse ONVIF response from {ip}: {e}")
    
    return None


def _extract_xml_field(text: str, tag_name: str) -> Optional[str]:
    """Extract an XML field value from the discovery response."""
    import re
    
    # Search for the tag with its content
    pattern = f"<{tag_name}>([^<]*)</{tag_name}>"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return None


def _extract_rtsp_url(text: str) -> Optional[str]:
    """Extract RTSP URL from ONVIF discovery response."""
    import re
    
    # Look for RTSP URI in the response
    patterns = [
        r"rtsp://[^\s'\"\>]+",
        r"s:URI> rtsp://[^\s<]+",
        r"Streaming/URI>[^\n]*rtsp:[^\n]*",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            url = match.group(0)
            # Clean up the URL
            url = re.sub(r"^.*?(rtsp://[^\s<]+).*$", r"\1", url, flags=re.DOTALL)
            if url.startswith("rtsp://"):
                return url
    
    return None


class OnvifDiscoveryError(Exception):
    """Raised when ONVIF discovery fails."""
    pass


class OnvifNotSupportedError(OnvifDiscoveryError):
    """Raised when ONVIF libraries are not available."""
    pass


# Export public API
__all__ = [
    "OnvifCameraInfo",
    "discover_onvif_cameras",
    "OnvifDiscoveryError",
    "OnvifNotSupportedError",
]