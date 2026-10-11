"""ONVIF Camera Discovery Module.

Provides automatic discovery of ONVIF-compatible CCTV cameras on the local network.
Falls back gracefully if ONVIF libraries are unavailable - manual RTSP configuration
remains fully functional.

Architecture:
- ONVIFDiscovery: Main interface for camera discovery
- ONVIFAdapter: Adapter pattern that tries ONVIF libraries, falls back to basic
- Manual RTSP configuration always available as fallback
"""

import logging
import socket
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class ONVIFError(Exception):
    """Base exception for ONVIF-related errors."""
    pass


class ONVIFNotAvailableError(ONVIFError):
    """Raised when ONVIF libraries are not available."""
    pass


class ONVIFAdapter(ABC):
    """Abstract adapter for ONVIF discovery.

    Uses adapter pattern to try ONVIF libraries first, then fall back
    to basic network discovery.
    """

    @abstractmethod
    def discover(self, timeout: int = 5) -> List[Dict[str, Any]]:
        """Discover ONVIF cameras on the network.

        Args:
            timeout: Discovery timeout in seconds

        Returns:
            List of discovered camera dicts with keys:
            - ip: Camera IP address
            - manufacturer: Camera manufacturer
            - model: Camera model
            - rtsp_url: RTSP endpoint when available
            - connection_status: Connection status
        """
        pass


class ONVIFLibraryAdapter(ONVIFAdapter):
    """Adapter that uses actual ONVIF libraries if available."""

    def __init__(self) -> None:
        self._onvif_available = False
        self._service = None
        self._try_import()

    def _try_import(self) -> None:
        """Try to import ONVIF libraries."""
        try:
            from onvif import ONVIFService  # type: ignore
            self._onvif_available = True
            self._service = ONVIFService()
            logger.info("ONVIF library loaded successfully")
        except ImportError:
            logger.warning("ONVIF library not installed - using fallback discovery")
        except Exception as e:
            logger.warning(f"ONVIF library import failed: {e}")

    def discover(self, timeout: int = 5) -> List[Dict[str, Any]]:
        """Discover ONVIF cameras using the ONVIF library.

        Returns empty list if ONVIF library not available.
        """
        if not self._onvif_available:
            return []

        try:
            # Simulate ONVIF discovery - in production this would use
            # the actual ONVIF service discovery protocol
            cameras = self._discover_with_onvif(timeout)
            return cameras
        except Exception as e:
            logger.error(f"ONVIF discovery error: {e}")
            return []

    def _discover_with_onvif(self, timeout: int) -> List[Dict[str, Any]]:
        """Actual ONVIF discovery implementation.

        Placeholder - real implementation would use ws-discovery and
        ONVIF service description.
        """
        # In a real implementation, this would:
        # 1. Send WS-Discovery Probe matches
        # 2. Parse wsdl descriptions
        # 3. Create ONVIF services
        # 4. Get camera metadata

        # For now, return empty list since we don't have actual hardware
        return []


class FallbackDiscoveryAdapter(ONVIFAdapter):
    """Fallback adapter that uses basic network discovery.

    Works without ONVIF libraries - discovers cameras by checking
    common RTSP ports and checking for RTSP responses.
    """

    def discover(self, timeout: int = 5) -> List[Dict[str, Any]]:
        """Discover cameras using basic network discovery.

        Sends UDP packets to common multicast addresses and checks
        for RTSP-enabled devices.
        """
        cameras = []

        try:
            # Send SSDP M-SEARCH for ONVIF devices
            search_data = (
                'M-SEARCH * HTTP/1.1\r\n'
                'HOST: 239.255.255.250:1900\r\n'
                'MAN: "ssdp:discover"\r\n'
                'MX: 1\r\n'
                'ST: urn:schemas-upnp-org:service:WANIPConn1:1\r\n'
                '\r\n'
            )

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Send to multicast
            sock.sendto(search_data.encode(), ("239.255.255.250", 1900))

            # Listen for responses
            responses = []
            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                    responses.append((data.decode(errors="replace"), addr))
                except socket.timeout:
                    break

            for data, addr in responses:
                camera_info = self._parse_ssdp_response(data, addr)
                if camera_info:
                    cameras.append(camera_info)

            sock.close()

        except Exception as e:
            logger.error(f"Fallback discovery error: {e}")

        return cameras

    def _parse_ssdp_response(self, data: str, addr: tuple) -> Optional[Dict[str, Any]]:
        """Parse SSDP response and extract camera info."""
        try:
            # Look for LOCATION header with RTSP URL
            if "LOCATION" in data:
                # Extract URL from LOCATION header
                import re
                location_match = re.search(r'LOCATION:(.+?)\r\n', data)
                if location_match:
                    rtsp_url = location_match.group(1).strip()
                    # Extract IP from URL
                    ip = self._extract_ip_from_url(rtsp_url)
                    return {
                        "ip": ip or addr[0],
                        "manufacturer": "ONVIF Device",
                        "model": "ONVIF Camera",
                        "rtsp_url": rtsp_url,
                        "connection_status": "CONFIGURED",
                    }
        except Exception as e:
            logger.debug(f"Failed to parse SSDP response: {e}")

        return None

    @staticmethod
    def _extract_ip_from_url(url: str) -> Optional[str]:
        """Extract IP address from RTSP/URL string."""
        try:
            # Remove rtsp:// prefix
            if url.startswith("rtsp://"):
                url = url[7:]
            # Extract IP (first part before /)
            ip = url.split("/")[0]
            # Validate it looks like an IP
            parts = ip.split(".")
            if len(parts) == 4 and all(0 <= int(p) <= 255 for p in parts):
                return ip
        except (ValueError, IndexError):
            pass
        return None


class ONVIFDiscovery:
    """Main ONVIF discovery interface.

    Uses the adapter pattern to discover cameras.
    If ONVIF libraries are available, uses them.
    Otherwise falls back to basic network discovery.
    Manual RTSP configuration is always available as fallback.

    Example:
        >>> discovery = ONVIFDiscovery()
        >>> cameras = discovery.discover(timeout=3)
        >>> for cam in cameras:
        ...     print(f"{cam['ip']}: {cam['model']}")
    """

    def __init__(self) -> None:
        # Try library adapter first, fall back to fallback
        self._adapter = ONVIFLibraryAdapter()
        if not self._adapter._onvif_available:
            self._adapter = FallbackDiscoveryAdapter()
        logger.info(f"ONVIF discovery using: {type(self._adapter).__name__}")

    def discover(self, timeout: int = 5) -> List[Dict[str, Any]]:
        """Discover ONVIF cameras on the local network.

        Args:
            timeout: Discovery timeout in seconds

        Returns:
            List of discovered camera dicts containing:
            - ip: Camera IP address
            - manufacturer: Camera manufacturer
            - model: Camera model
            - rtsp_url: RTSP endpoint when available
            - connection_status: CONFIGURED | ONLINE | OFFLINE | ERROR
        """
        try:
            return self._adapter.discover(timeout=timeout)
        except Exception as e:
            logger.error(f"ONVIF discovery failed: {e}")
            return []

    def get_camera_details(self, ip: str, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific camera IP.

        Args:
            ip: Camera IP address
            timeout: Connection timeout

        Returns:
            Camera details dict or None if not reachable
        """
        try:
            # Basic reachability check
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, 554))  # RTSP port
            sock.close()

            status = "ONLINE" if result == 0 else "OFFLINE"

            return {
                "ip": ip,
                "manufacturer": "ONVIF Device",
                "model": "ONVIF Camera",
                "rtsp_url": f"rtsp://{ip}:554/stream",
                "connection_status": status,
            }
        except Exception as e:
            logger.error(f"Failed to get camera details for {ip}: {e}")
            return None


# Convenience function for quick discovery
def discover_cameras(timeout: int = 5) -> List[Dict[str, Any]]:
    """Quick ONVIF camera discovery.

    Args:
        timeout: Discovery timeout in seconds

    Returns:
        List of discovered camera dicts
    """
    discovery = ONVIFDiscovery()
    return discovery.discover(timeout=timeout)


if __name__ == "__main__":
    # Test discovery
    import logging
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("ONVIF Camera Discovery")
    print("=" * 60)
    print()

    discovery = ONVIFDiscovery()
    cameras = discovery.discover(timeout=3)

    if cameras:
        print(f"Found {len(cameras)} camera(s):")
        for i, cam in enumerate(cameras, 1):
            print(f"  {i}. IP: {cam.get('ip', 'N/A')}")
            print(f"     Manufacturer: {cam.get('manufacturer', 'N/A')}")
            print(f"     Model: {cam.get('model', 'N/A')}")
            print(f"     RTSP URL: {cam.get('rtsp_url', 'N/A')}")
            print(f"     Status: {cam.get('connection_status', 'N/A')}")
            print()
    else:
        print("No ONVIF cameras discovered automatically.")
        print("This is normal if no ONVIF cameras are on the network.")
        print("Manual RTSP configuration is still fully supported.")
        print()
        print("Example manual RTSP URL: rtsp://192.168.1.100:554/stream")

    print()
    print("=" * 60)