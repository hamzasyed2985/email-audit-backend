import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class GlockAppsAPI:
    """Handles GlockApps API operations"""
    
    def __init__(self, api_key: str, folder_id: str = None):
        self.api_key = api_key
        self.base_url = "https://api.glockapps.com/gateway/spamtest-v2/api"
        self.headers_variants = [
            {"x-api-key": api_key, "Content-Type": "application/json"},
            {"X-API-Key": api_key, "Content-Type": "application/json"},
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            {"api-key": api_key, "Content-Type": "application/json"}
        ]
        self.current_header_index = 0
        self.headers = self.headers_variants[self.current_header_index]
        
        # Provider group IDs from the API documentation
        self.provider_group_ids = [

            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "11",
            "13",
            "17",
            "19",
            "24",
            "25",
            "30",
            "33",
            "34",
            "42",
            "45",
            "47",
            "50",
            "52",
            "53",
            "54",
            "55",
            "56",
            "57",
            "59",
            "60",
            "61",
            "62",
            "63",
            "64",
        ]

        
        # Folder ID from environment variable or parameter
        if folder_id:
            self.folder_id = folder_id
        else:
            import os
            self.folder_id = os.getenv("GLOCKAPPS_FOLDER_ID", "")
    
    def test_api_connection(self) -> bool:
        """Test GlockApps API connection"""
        logger.info("Testing GlockApps API connection...")
        
        for i, headers in enumerate(self.headers_variants):
            try:
                response = requests.get(
                    f"{self.base_url}/projects",
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ GlockApps API connection successful with headers variant {i+1}")
                    self.current_header_index = i
                    self.headers = headers
                    return True
                else:
                    logger.warning(f"⚠️ GlockApps API returned status {response.status_code}: {response.text}")
                    
            except Exception as e:
                logger.warning(f"⚠️ GlockApps API connection failed with headers variant {i+1}: {e}")
        
        logger.error("❌ GlockApps API connection failed. Please check your API key and try again.")
        return False
    
    def _make_request_with_retry(self, method: str, endpoint: str, **kwargs) -> Optional[requests.Response]:
        """Make API request with retry mechanism for different header variants"""
        for i, headers in enumerate(self.headers_variants):
            try:
                kwargs['headers'] = headers
                response = requests.request(method, endpoint, **kwargs)
                
                if response.status_code in [200, 201]:
                    logger.info(f"Request successful with headers variant {i+1}")
                    self.current_header_index = i
                    self.headers = headers
                    return response
                elif response.status_code in [401, 500] and "No API key provided" in response.text:
                    logger.warning(f"Authentication failed with headers variant {i+1}, trying next...")
                    continue
                else:
                    logger.info(f"Request completed - Status: {response.status_code}")
                    return response
                    
            except Exception as e:
                logger.warning(f"Request failed with headers variant {i+1}: {e}")
                continue
        
        logger.error("All header variants failed")
        return None
    
    def _get_project_id(self) -> Optional[str]:
        """Get project ID from GlockApps"""
        try:
            response = self._make_request_with_retry(
                "GET", 
                f"{self.base_url}/projects"
            )
            
            if not response:
                return None
            
            if response.status_code == 200:
                result = response.json()
                
                # Handle different response structures
                if isinstance(result, dict) and "results" in result:
                    projects = result["results"]
                elif isinstance(result, list):
                    projects = result
                else:
                    logger.error(f"Unexpected response structure: {result}")
                    return None
                
                if projects:
                    # Try to get project ID from first project
                    project = projects[0]
                    project_id = project.get("id") or project.get("projectId")
                    
                    if project_id:
                        logger.info(f"Retrieved project ID: {project_id}")
                        return str(project_id)
                    else:
                        logger.error(f"No project ID found in project data: {project}")
                        return None
                else:
                    logger.error("No projects found in response")
                    return None
            else:
                logger.error(f"Failed to get projects: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting project ID: {e}")
            return None
    
    def create_test(self, domain: str, from_email: str) -> Dict[str, Any]:
        """Create a test in GlockApps"""
        logger.info(f"Creating GlockApps test for domain: {domain}")
        
        try:
            project_id = self._get_project_id()
            if not project_id:
                raise Exception("Could not retrieve project ID from GlockApps")
            
            payload = {
                "providerGroupIds": self.provider_group_ids,
                "testType": "ManualTest",
                "folderId": self.folder_id,
                "linkChecker": True,
                "note": f"Email audit test for {domain}"
            }
            
            response = self._make_request_with_retry(
                "POST",
                f"{self.base_url}/projects/{project_id}/manualTest",
                json=payload
            )
            
            if not response:
                raise Exception("API request failed: No response")
            
            if response.status_code in [200, 201]:
                result = response.json()
                test_id = result.get('testId')
                emails = result.get('emails', [])
                
                if test_id:
                    logger.info(f"Successfully created test with ID: {test_id}")
                    logger.info(f"Test includes {len(emails)} email addresses")
                    return {
                        "test_id": test_id,
                        "status": "created",
                        "emails": emails,
                        "response": result
                    }
                else:
                    raise Exception(f"No test ID in response: {result}")
            else:
                raise Exception(f"API request failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Failed to create test: {e}")
            raise
    
    def get_seed_list(self, test_id: str) -> List[str]:
        """Get seed list for a test"""
        # Note: The seed list is returned directly in the test creation response
        # This method is kept for compatibility but the emails are already available
        logger.warning("Seed list should be retrieved from test creation response, not separate API call")
        return []
    
    def check_test_status(self, test_id: str) -> Dict[str, Any]:
        """Check test status using the correct endpoint structure"""
        try:
            # First get the project ID
            project_id = self._get_project_id()
            if not project_id:
                raise Exception("Could not retrieve project ID from GlockApps")
            
            # Use the correct endpoint: /projects/{projectId}/tests?testId={testId}
            response = self._make_request_with_retry(
                "GET",
                f"{self.base_url}/projects/{project_id}/tests?testId={test_id}",
                timeout=10
            )
            
            if not response:
                raise Exception("API request failed: No response")
            
            if response.status_code == 200:
                result = response.json()
                
                # Extract status from the response structure
                # Based on the image, we need to check if 'finished' is true
                finished = result.get('finished', False)
                status = "completed" if finished else "running"
                
                logger.info(f"Test {test_id} status: {status} (finished: {finished})")
                return {"status": status, "data": result}
            else:
                raise Exception(f"Failed to check test status: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error checking test status: {e}")
            raise
    
    def get_test_results(self, test_id: str) -> Dict[str, Any]:
        """Get test results using the correct endpoint structure"""
        try:
            # First get the project ID
            project_id = self._get_project_id()
            if not project_id:
                raise Exception("Could not retrieve project ID from GlockApps")
            
            # Use the correct endpoint: /projects/{projectId}/tests?testId={testId}
            response = self._make_request_with_retry(
                "GET",
                f"{self.base_url}/projects/{project_id}/tests?testId={test_id}",
                timeout=10
            )
            
            if not response:
                raise Exception("API request failed: No response")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Retrieved test results for test: {test_id}")
                
                # Check if test is finished before saving/processing
                if result.get('finished', False):
                    logger.info(f"Test {test_id} is completed (finished: true)")
                    return result
                else:
                    logger.info(f"Test {test_id} is still running (finished: {result.get('finished')}), will check again later")
                    # Return a special status to indicate test is not ready
                    return {"status": "not_ready", "finished": False, "message": "Test still running"}
            else:
                raise Exception(f"Failed to get test results: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error getting test results: {e}")
            raise

    def check_test_completion_stability(self, test_id: str, not_delivered_history: List[int]) -> Dict[str, Any]:
        """Check test completion using notDelivered count stability (3 successive same values)"""
        try:
            # First get the project ID
            project_id = self._get_project_id()
            if not project_id:
                raise Exception("Could not retrieve project ID from GlockApps")
            
            # Use the correct endpoint: /projects/{projectId}/tests?testId={testId}
            response = self._make_request_with_retry(
                "GET",
                f"{self.base_url}/projects/{project_id}/tests?testId={test_id}",
                timeout=10
            )
            
            if not response:
                raise Exception("API request failed: No response")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Retrieved test results for test: {test_id}")
                
                # FIRST: Check if test is finished immediately - this should be the primary check
                if result.get('result', {}).get('finished', False):
                    logger.info(f"Test {test_id} is completed (finished: true)")
                    return {"status": "completed", "finished": True, "data": result}
                
                # SECOND: Only if finished is false, then check notDelivered stability
                # Get current notDelivered count - stats are nested under 'result' key
                stats = result.get('result', {}).get('stats', {})
                current_not_delivered = stats.get('notDelivered', 0)
                
                # Add to history
                not_delivered_history.append(current_not_delivered)
                
                # Keep only last 3 values
                if len(not_delivered_history) > 3:
                    not_delivered_history.pop(0)
                
                logger.info(f"Test {test_id} - notDelivered history: {not_delivered_history}")
                
                # Check if we have 3 values and they're all the same (stability)
                if len(not_delivered_history) == 3 and len(set(not_delivered_history)) == 1:
                    logger.info(f"Test {test_id} is stable with notDelivered={current_not_delivered} for 3 checks, processing as complete")
                    return {"status": "completed", "finished": False, "data": result, "stable_not_delivered": current_not_delivered}
                else:
                    logger.info(f"Test {test_id} notDelivered count: {current_not_delivered}, history: {not_delivered_history}, will check again in 15 seconds")
                    return {"status": "not_ready", "finished": False, "not_delivered_history": not_delivered_history, "message": "Waiting for stability"}
            else:
                raise Exception(f"Failed to get test results: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error checking test completion stability: {e}")
            raise
    

