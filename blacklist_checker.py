import os
import socket
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class BlacklistChecker:
    """Handles IP and Domain blacklist checking via blacklistchecker.com API"""
    
    def __init__(self, api_key: str = None):
        self.base_url = "https://api.blacklistchecker.com"
        self.api_key = api_key or os.getenv("BLACKLIST_CHECKER_API_KEY", "")
        self.session = requests.Session()
        self.session.auth = (self.api_key, '')
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def get_domain_ip(self, domain: str) -> Optional[str]:
        """Resolve domain to IP address"""
        try:
            ip = socket.gethostbyname(domain)
            logger.info(f"Resolved {domain} to IP: {ip}")
            return ip
        except socket.gaierror as e:
            logger.error(f"Could not resolve domain {domain}: {e}")
            return None
    
    def check_ip_blacklists(self, ip_address: str) -> Dict[str, Any]:
        """Check IP address against blacklists"""
        url = f"{self.base_url}/check/{ip_address}"
        logger.info(f"Checking IP at: {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"IP blacklist check completed for {ip_address}")
                
                # Parse the official API response format
                detections = result.get('detections', 0)
                blacklists = result.get('blacklists', [])
                checks_remaining = result.get('checks_remaining', 0)
                
                # Check if any blacklists detected the IP
                detected_blacklists = [bl for bl in blacklists if bl.get('detected', False)]
                
                return {
                    "ip_address": ip_address,
                    "status": "checked",
                    "blacklisted": detections > 0,
                    "detections": detections,
                    "blacklists": detected_blacklists,
                    "total_blacklists_checked": len(blacklists),
                    "checks_remaining": checks_remaining,
                    "raw_response": result,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                error_data = response.json() if response.text else {}
                logger.warning(f"IP blacklist check failed with status {response.status_code}: {error_data}")
                
                return {
                    "ip_address": ip_address,
                    "status": "failed",
                    "error": f"HTTP {response.status_code}",
                    "error_details": error_data,
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error checking IP blacklists for {ip_address}: {e}")
            
            return {
                "ip_address": ip_address,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def check_domain_blacklists(self, domain: str) -> Dict[str, Any]:
        """Check domain against blacklists"""
        url = f"{self.base_url}/check/{domain}"
        logger.info(f"Checking domain at: {url}")
        
        try:
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Domain blacklist check completed for {domain}")
                
                # Parse the official API response format
                detections = result.get('detections', 0)
                blacklists = result.get('blacklists', [])
                checks_remaining = result.get('checks_remaining', 0)
                input_type = result.get('input_type', 'unknown')
                
                # Check if any blacklists detected the domain
                detected_blacklists = [bl for bl in blacklists if bl.get('detected', False)]
                
                return {
                    "domain": domain,
                    "status": "checked",
                    "blacklisted": detections > 0,
                    "detections": detections,
                    "blacklists": detected_blacklists,
                    "total_blacklists_checked": len(blacklists),
                    "checks_remaining": checks_remaining,
                    "input_type": input_type,
                    "raw_response": result,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                error_data = response.json() if response.text else {}
                logger.warning(f"Domain blacklist check failed with status {response.status_code}: {error_data}")
                
                return {
                    "domain": domain,
                    "status": "failed",
                    "error": f"HTTP {response.status_code}",
                    "error_details": error_data,
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error checking domain blacklists for {domain}: {e}")
            
            return {
                "domain": domain,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
