import os
import sys
import subprocess
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from notion_client import Client
from dotenv import load_dotenv

# Import modular components
from notion_manager import NotionManager
from blacklist_checker import BlacklistChecker
from glockapps_api import GlockAppsAPI
from postmark_checker import PostmarkChecker
from report_generator import ReportGenerator

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_AUDITS_DB_ID = os.getenv("NOTION_AUDITS_DB_ID")
GLOCKAPPS_API_KEY = os.getenv("GLOCKAPPS_API_KEY")
GLOCKAPPS_FOLDER_ID = os.getenv("GLOCKAPPS_FOLDER_ID")

# Initialize clients
notion = Client(auth=NOTION_API_KEY)

class EmailAuditEngine:
    """Main engine that orchestrates the email audit process"""
    
    def __init__(self):
        self.glockapps = GlockAppsAPI(GLOCKAPPS_API_KEY, GLOCKAPPS_FOLDER_ID)
        self.notion = NotionManager(notion, NOTION_AUDITS_DB_ID)
        self.blacklist_checker = BlacklistChecker()  # Uses default API key from environment or hardcoded
        self.postmark_checker = PostmarkChecker()  # PostmarkApp integration
        self.report_generator = ReportGenerator()  # Report generation
    
    def _append_error_log(self, page_id: str, error_message: str) -> None:
        """Append error message to Error Log field in Notion (only for main step failures)"""
        try:
            # Get current Error Log content
            audit_page = self.notion.client.pages.retrieve(page_id)
            error_log_property = audit_page.get("properties", {}).get("Error Log", {})
            rich_text = error_log_property.get("rich_text", [])
            
            # Safely get current content
            current_error_log = ""
            if rich_text and len(rich_text) > 0:
                current_error_log = rich_text[0].get("text", {}).get("content", "")
            
            # Append new error with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if current_error_log:
                new_error_log = f"{current_error_log}\n[{timestamp}] {error_message}"
            else:
                new_error_log = f"[{timestamp}] {error_message}"
            
            # Update Error Log field
            self.notion.update_audit_fields(page_id, {
                "Error Log": {"rich_text": [{"text": {"content": new_error_log}}]}
            })
            
            logger.info(f"✅ Appended error to Error Log: {error_message}")
            
        except Exception as e:
            logger.error(f"Failed to append error to Error Log: {e}")
    
    def process_running_audits(self):
        """Main function to process ONE running audit completely before moving to next"""
        logger.info("Checking for running audits...")
        
        running_audits = self.notion.get_running_audits()
        
        if not running_audits:
            logger.info("No running audits found")
            return False  # No audits to process
        
        # Process only ONE audit at a time
        audit = running_audits[0]
        logger.info(f"Processing ONE audit: {audit.get('properties', {}).get('Audit ID', {}).get('title', [{}])[0].get('plain_text', 'Unknown')}")
        
        try:
            self.process_single_audit(audit)
            logger.info("✅ Audit processing completed successfully")
            return True  # Audit was processed
        except Exception as e:
            logger.error(f"Error processing audit {audit.get('id')}: {e}")
            return False  # Audit processing failed
    
    def process_single_audit(self, audit: Dict[str, Any]):
        """Process a single audit record"""
        page_id = audit["id"]
        props = audit["properties"]
        
        # Extract audit information
        audit_id = props.get("Audit ID", {}).get("title", [{}])[0].get("plain_text", "Unknown")
        domain_relation = props.get("Domain", {}).get("relation", [])
        
        if not domain_relation:
            logger.warning(f"Audit {audit_id} has no domain relation")
            return
        
        domain_relation_id = domain_relation[0]["id"]
        domain_name = self.notion.get_domain_info(domain_relation_id)
        
        if not domain_name:
            logger.warning(f"Could not get domain name for audit {audit_id}")
            return
        
        logger.info(f"Processing audit {audit_id} for domain {domain_name}")
        
        # Step 1: Check IP and Domain Blacklists FIRST
        logger.info("=== STEP 1: Checking Blacklists ===")
        
        # Get IP address from domain using DNS lookup
        ip_address = self.blacklist_checker.get_domain_ip(domain_name)
        
        if not ip_address:
            logger.error(f"Could not resolve IP for domain {domain_name}")
            # Update Notion with error
            error_properties = {
                "IP Blacklist Status": {"rich_text": [{"text": {"content": "Error: Could not resolve IP"}}]},
                "Domain Blacklist Status": {"rich_text": [{"text": {"content": "Error: Could not resolve IP"}}]},
                "Audit Status": {"select": {"name": "Error"}}
            }
            self.notion.update_audit_fields(page_id, error_properties)
            self._append_error_log(page_id, "Blacklist Checker Failed")
            return
        
        # Check IP blacklists
        logger.info(f"Checking IP blacklists for: {ip_address}")
        ip_blacklist_result = self.blacklist_checker.check_ip_blacklists(ip_address)
        logger.info(f"IP Blacklist check result: {ip_blacklist_result}")
        
        # Check Domain blacklists
        logger.info(f"Checking domain blacklists for: {domain_name}")
        domain_blacklist_result = self.blacklist_checker.check_domain_blacklists(domain_name)
        logger.info(f"Domain Blacklist check result: {domain_blacklist_result}")
        
        # Update Notion with detailed blacklist results
        blacklist_properties = {}
        
        # Handle IP Blacklist Status
        ip_detections = ip_blacklist_result.get('detections', 0)
        if ip_blacklist_result.get('status') == 'fallback':
            blacklist_properties["IP Blacklist Status"] = {"rich_text": [{"text": {"content": "Fallback - Check Failed"}}]}
            blacklist_properties["Issues Found"] = {"rich_text": [{"text": {"content": "IP Blacklist check failed, using fallback values"}}]}
        elif ip_blacklist_result.get('blacklisted'):
            # Get specific blacklist names where IP was detected
            detected_bls = [bl.get('name', bl.get('id', 'Unknown')) for bl in ip_blacklist_result.get('blacklists', [])]
            blacklist_properties["IP Blacklist Status"] = {"rich_text": [{"text": {"content": f"BLACKLISTED ({ip_detections} detections): {', '.join(detected_bls)}"}}]}
            
            # Add detected blacklists to Issues Found field
            if detected_bls:
                blacklist_properties["Issues Found"] = {"rich_text": [{"text": {"content": f"IP Blacklisted on: {', '.join(detected_bls)}"}}]}
        else:
            blacklist_properties["IP Blacklist Status"] = {"rich_text": [{"text": {"content": f"Detections: {ip_detections}"}}]}
        
        # Handle Domain Blacklist Status
        domain_detections = domain_blacklist_result.get('detections', 0)
        if domain_blacklist_result.get('status') == 'fallback':
            domain_status = blacklist_properties.get("Domain Blacklist Status", {})
            if not domain_status:
                blacklist_properties["Domain Blacklist Status"] = {"rich_text": [{"text": {"content": "Fallback - Check Failed"}}]}
            current_issues = blacklist_properties.get("Issues Found", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
            domain_issues = "Domain Blacklist check failed, using fallback values"
            
            if current_issues:
                blacklist_properties["Issues Found"]["rich_text"][0]["text"]["content"] = f"{current_issues}; {domain_issues}"
            else:
                blacklist_properties["Issues Found"] = {"rich_text": [{"text": {"content": domain_issues}}]}
        elif domain_blacklist_result.get('blacklisted'):
            # Get specific blacklist names where domain was detected
            detected_bls = [bl.get('name', bl.get('id', 'Unknown')) for bl in domain_blacklist_result.get('blacklists', [])]
            blacklist_properties["Domain Blacklist Status"] = {"rich_text": [{"text": {"content": f"BLACKLISTED ({domain_detections} detections): {', '.join(detected_bls)}"}}]}
            
            # Add detected blacklists to Issues Found field
            if detected_bls:
                current_issues = blacklist_properties.get("Issues Found", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
                domain_issues = f"Domain Blacklisted on: {', '.join(detected_bls)}"
                
                if current_issues:
                    blacklist_properties["Issues Found"]["rich_text"][0]["text"]["content"] = f"{current_issues}; {domain_issues}"
                else:
                    blacklist_properties["Issues Found"] = {"rich_text": [{"text": {"content": domain_issues}}]}
        else:
            blacklist_properties["Domain Blacklist Status"] = {"rich_text": [{"text": {"content": f"Detections: {domain_detections}"}}]}
        
        # Add checks remaining information
        if ip_blacklist_result.get('status') == 'fallback':
            ip_checks = 'Fallback - Check Failed'
        else:
            ip_checks = ip_blacklist_result.get('checks_remaining', 'Unknown')
            
        if domain_blacklist_result.get('status') == 'fallback':
            domain_checks = 'Fallback - Check Failed'
        else:
            domain_checks = domain_blacklist_result.get('checks_remaining', 'Unknown')
            
        blacklist_properties["Raw JSON Output"] = {"rich_text": [{"text": {"content": f"IP Checks Remaining: {ip_checks}, Domain Checks Remaining: {domain_checks}"}}]}
        
        # Check if blacklist checks failed and handle accordingly
        if ip_blacklist_result.get('status') in ['failed', 'error'] or domain_blacklist_result.get('status') in ['failed', 'error']:
            logger.warning(f"⚠️ Blacklist checks failed for domain {domain_name}, but continuing with fallback values")
            self._append_error_log(page_id, "Blacklist Checker Failed")
            # Use fallback values instead of stopping the audit
            if ip_blacklist_result.get('status') in ['failed', 'error']:
                ip_blacklist_result = {
                    'status': 'fallback',
                    'blacklists': [],
                    'timestamp': datetime.now().isoformat()
                }
            if domain_blacklist_result.get('status') in ['failed', 'error']:
                domain_blacklist_result = {
                    'status': 'fallback', 
                    'blacklists': [],
                    'timestamp': datetime.now().isoformat()
                }
            logger.info(f"✅ Using fallback blacklist values for domain {domain_name}")
        
        self.notion.update_audit_fields(page_id, blacklist_properties)
        logger.info("Blacklist checks completed and Notion updated")
        
        # Step 2: Create test in GlockApps (continues even if blacklist failed)
        logger.info("=== STEP 2: Creating GlockApps Test ===")
        
        try:
            logger.info(f"Creating GlockApps test for domain: {domain_name}")
            logger.info(f"Using from_email: audit@{domain_name}")
            
            test_result = self.glockapps.create_test(
                domain=domain_name,
                from_email=f"audit@{domain_name}"
            )
            
            test_id = test_result.get("test_id") or test_result.get("id")
            
            if not test_id:
                logger.error(f"No test ID returned from GlockApps for audit {audit_id}")
                logger.error(f"Full response: {test_result}")
                return
            
            logger.info(f"Successfully created test with ID: {test_id}")
            
            # Step 3: Get seed list from test creation response
            # The seed list is returned directly when creating the test
            seed_list = test_result.get("emails", [])
            logger.info(f"Seed list from test creation: {len(seed_list)} addresses")
            
            if not seed_list:
                logger.warning("No seed list found in test creation response")
                seed_list = []
            
            # Step 4: Update Notion with test ID and seed list
            # Split seed list into 4 chunks of 25 addresses each
            def split_seed_list(seed_list, chunk_size=25, max_chunks=5):
                """Split seed list into chunks for separate Notion fields"""
                if not seed_list:
                    return ["Failed to retrieve"] * max_chunks
                
                chunks = []
                for i in range(0, len(seed_list), chunk_size):
                    chunk = seed_list[i:i + chunk_size]
                    chunks.append(", ".join(chunk))
                
                # Pad with empty strings if we have fewer than max_chunks
                while len(chunks) < max_chunks:
                    chunks.append("")
                
                # Truncate if we have more than max_chunks
                return chunks[:max_chunks]
            
            seed_chunks = split_seed_list(seed_list)
            
            update_properties = {
                "GlockApps Test ID": {"rich_text": [{"text": {"content": test_id}}]},
                "GlockApps Seed List 1": {"rich_text": [{"text": {"content": seed_chunks[0]}}]},
                "GlockApps Seed List 2": {"rich_text": [{"text": {"content": seed_chunks[1]}}]},
                "GlockApps Seed List 3": {"rich_text": [{"text": {"content": seed_chunks[2]}}]},
                "GlockApps Seed List 4": {"rich_text": [{"text": {"content": seed_chunks[3]}}]},
                "GlockApps Seed List 5": {"rich_text": [{"text": {"content": seed_chunks[4]}}]},
                "Audit Status": {"select": {"name": "Test Created"}}
            }
            
            self.notion.update_audit_fields(page_id, update_properties)
            logger.info(f"Successfully created test {test_id} for audit {audit_id}")
            
            # Step 5: Update status to await manual email sending
            logger.info("=== STEP 5: Awaiting Manual Email Sending ===")
            logger.info(f"Audit {audit_id} is ready for Mr. Dill to send emails manually")
            
            # Update Notion status to await manual email sending
            email_status_properties = {
                "Audit Status": {"select": {"name": "Awaiting Email Sending"}}
            }
            self.notion.update_audit_fields(page_id, email_status_properties)
            
            logger.info(f"✅ Audit {audit_id} marked as 'Awaiting Email Sending'")
            logger.info(f"🔄 Mr. Dill should now send emails manually and change status to 'Emails Sent'")
            
        except Exception as e:
            logger.error(f"❌ Exception during GlockApps test creation: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception details: {e}")
            
            # Use fallback values instead of stopping the audit
            logger.warning(f"⚠️ GlockApps test creation failed for domain {domain_name}, but continuing with fallback values")
            
            # Create fallback GlockApps data
            fallback_test_id = f"fallback_{int(time.time())}"
            fallback_seed_list = []
            
            # Update Notion with fallback values and mark as "GlockApps Completed"
            fallback_properties = {
                "GlockApps Test ID": {"rich_text": [{"text": {"content": fallback_test_id}}]},
                "GlockApps Seed List 1": {"rich_text": [{"text": {"content": "Fallback - GlockApps failed"}}]},
                "GlockApps Seed List 2": {"rich_text": [{"text": {"content": ""}}]},
                "GlockApps Seed List 3": {"rich_text": [{"text": {"content": ""}}]},
                "GlockApps Seed List 4": {"rich_text": [{"text": {"content": ""}}]},
                "GlockApps Seed List 5": {"rich_text": [{"text": {"content": ""}}]},
                "Audit Status": {"select": {"name": "GlockApps Completed"}},
                "Inbox Placement %": {"number": 0},
                "Spam Placement %": {"number": 0}
            }
            self.notion.update_audit_fields(page_id, fallback_properties)
            self._append_error_log(page_id, "GlockApps Failed")
            logger.info(f"✅ Using fallback GlockApps values for domain {domain_name}")
            
            # Let the normal workflow continue - don't automatically set to "Emails Sent"
            logger.info("=== STEP 5: GlockApps Failed - Using Fallback Values ===")
            logger.info(f"Audit {audit_id} marked as 'GlockApps Completed' with fallback data")
            logger.info(f"🔄 Normal workflow will continue to PostmarkApp step...")
            
            # Continue to next step instead of stopping
            return
    
    def _handle_fallback_glockapps_audits(self):
        """Handle fallback GlockApps audits by moving them to PostmarkApp step"""
        try:
            # Get audits with "GlockApps Completed" status that have fallback test IDs
            response = self.notion.client.databases.query(
                database_id=self.notion.database_id,
                filter={"property": "Audit Status", "select": {"equals": "GlockApps Completed"}}
            )
            glockapps_completed_audits = response.get("results", [])
            
            for audit in glockapps_completed_audits:
                page_id = audit["id"]
                props = audit["properties"]
                
                # Check if this is a fallback test ID
                test_id_field = props.get("GlockApps Test ID", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
                
                if test_id_field.startswith("fallback_"):
                    logger.info(f"🚀 Processing fallback GlockApps audit {page_id} - moving to PostmarkApp step")
                    
                    # Create fallback GlockApps results structure for PostmarkApp
                    fallback_glockapps_results = {
                        "test_id": test_id_field,  # Use the fallback test ID
                        "result": {
                            "stats": {
                                "inboxRate": 0,  # Fallback values
                                "spamRate": 0,
                                "notDeliveredRate": 0
                            }
                        }
                    }
                    
                    # Run PostmarkApp for this fallback audit
                    try:
                        self._run_postmark_deliverability_check(page_id, fallback_glockapps_results)
                        logger.info(f"✅ Fallback GlockApps audit {page_id} moved to PostmarkApp step")
                    except Exception as e:
                        logger.error(f"Error running PostmarkApp for fallback audit {page_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Error handling fallback GlockApps audits: {e}")

    def check_completed_tests(self):
        """Check for completed tests and update results"""
        logger.info("Checking for completed tests...")

        # Step 1: Get audits with "Emails Sent" status - these are ready for GlockApps report retrieval (after Mr. Dill manually sends emails)
        try:
            response = self.notion.client.databases.query(
                database_id=self.notion.database_id,
                filter={"property": "Audit Status", "select": {"equals": "Emails Sent"}}
            )
            emails_sent_audits = response.get("results", [])
            logger.info(f"Found {len(emails_sent_audits)} audits with emails sent, checking for GlockApps reports...")
        except Exception as e:
            logger.error(f"Error querying for emails sent audits: {e}")
            return

        for audit in emails_sent_audits:
            try:
                self.get_test_report(audit)
            except Exception as e:
                logger.error(f"Error getting test report for audit {audit.get('id')}: {e}")

        # Step 2: Get audits with "GlockApps Completed" status - these are ready for PostmarkApp
        try:
            response = self.notion.client.databases.query(
                database_id=self.notion.database_id,
                filter={"property": "Audit Status", "select": {"equals": "GlockApps Completed"}}
            )
            glockapps_completed_audits = response.get("results", [])
            if glockapps_completed_audits:
                # Process only the FIRST audit that needs PostmarkApp
                audit = glockapps_completed_audits[0]
                page_id = audit["id"]
                
                logger.info(f"🚀 Starting PostmarkApp for audit {page_id}...")
                
                try:
                    # Get GlockApps results from Notion for this audit
                    audit_page = self.notion.client.pages.retrieve(page_id)
                    props = audit_page.get("properties", {})
                    
                    # Extract GlockApps results from Notion fields
                    test_id = props.get("GlockApps Test ID", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "Unknown")
                    glockapps_results = {
                        "test_id": test_id,
                        "result": {
                            "stats": {
                                "inboxRate": props.get("Inbox Placement %", {}).get("number", 0),
                                "spamRate": props.get("Spam Placement %", {}).get("number", 0),
                                "notDeliveredRate": 0  # Default value
                            }
                        }
                    }
                    
                    # Run PostmarkApp for this ONE audit
                    self._run_postmark_deliverability_check(page_id, glockapps_results)
                    
                except Exception as e:
                    logger.error(f"Error running PostmarkApp for audit {page_id}: {e}")
            else:
                logger.info("No audits with 'GlockApps Completed' status found")
                
        except Exception as e:
            logger.error(f"Error querying for GlockApps completed audits: {e}")
            return

        # Step 3: Get audits with "Postmark Completed" status - these are ready for Postmaster
        try:
            response = self.notion.client.databases.query(
                database_id=self.notion.database_id,
                filter={"property": "Audit Status", "select": {"equals": "Postmark Completed"}}
            )
            postmark_completed_audits = response.get("results", [])
            if postmark_completed_audits:
                # Process only the FIRST audit that needs Postmaster
                audit = postmark_completed_audits[0]
                page_id = audit["id"]
                
                logger.info(f"🚀 Starting Postmaster for audit {page_id}...")
                
                try:
                    # Get PostmarkApp results from Notion for this audit
                    audit_page = self.notion.client.pages.retrieve(page_id)
                    props = audit_page.get("properties", {})
                    
                    # Extract PostmarkApp results from Notion fields
                    postmark_results = {
                        "spam_score": props.get("Content Spam Score", {}).get("number", 0),
                        "deliverability_status": "Unknown",  # Default value
                        "status": "success"  # Default to success for Postmaster step
                    }
                    
                    # Run Postmaster for this ONE audit
                    self._update_notion_with_postmark_results(page_id, postmark_results)
                    
                except Exception as e:
                    logger.error(f"Error running Postmaster for audit {page_id}: {e}")
            else:
                logger.info("No audits with 'Postmark Completed' status found")
                
        except Exception as e:
            logger.error(f"Error querying for Postmark completed audits: {e}")
            return

    def get_test_report(self, audit: Dict[str, Any]):
        """Get test report directly for an audit with 'Emails Sent' status (after Mr. Dill manually sends emails)"""
        page_id = audit["id"]
        props = audit["properties"]

        # Get audit ID for logging
        audit_id = props.get("Audit ID", {}).get("title", [{}])[0].get("plain_text", "Unknown")

        # Get test ID
        test_id_field = props.get("GlockApps Test ID", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")

        if not test_id_field:
            logger.warning(f"Audit {audit_id} has no test ID")
            return

        # Check if this is a fallback test ID (skip GlockApps API calls for fallback tests)
        if test_id_field.startswith("fallback_"):
            logger.info(f"Audit {audit_id} has fallback test ID {test_id_field}, skipping GlockApps report retrieval")
            # Mark as ready for next step (PostmarkApp)
            fallback_properties = {
                "Audit Status": {"select": {"name": "GlockApps Completed"}},
                "Inbox Placement %": {"number": 0},  # Fallback values
                "Spam Placement %": {"number": 0}
            }
            self.notion.update_audit_fields(page_id, fallback_properties)
            self._append_error_log(page_id, "GlockApps Failed")
            logger.info(f"✅ Fallback audit {audit_id} marked as 'GlockApps Completed' with fallback values")
            return

        logger.info(f"Getting test report for audit {audit_id} with test ID: {test_id_field}")

        # Check if we already have a tracking entry for this test
        if not hasattr(self, '_test_tracking'):
            self._test_tracking = {}
        
        if test_id_field not in self._test_tracking:
            # Initialize tracking for this test
            self._test_tracking[test_id_field] = {
                'not_delivered_history': [],
                'last_check_time': 0,
                'check_interval': 10  # 10 seconds
            }

        tracking = self._test_tracking[test_id_field]
        current_time = time.time()
        
        # Check if enough time has passed since last check (15 seconds)
        if current_time - tracking['last_check_time'] < tracking['check_interval']:
            return  # Not time to check yet
        
        # Update last check time
        tracking['last_check_time'] = current_time

        # Use the new stability checking method
        try:
            results = self.glockapps.check_test_completion_stability(
                test_id_field, 
                tracking['not_delivered_history']
            )
            
            # Update tracking with new history
            if 'not_delivered_history' in results:
                tracking['not_delivered_history'] = results['not_delivered_history']
            
            # Check if test is ready for processing
            if results.get("status") == "not_ready":
                logger.info(f"Test {test_id_field} waiting for stability, will check again in 10 seconds")
                return  # Don't update anything, just return
            
            # Test is complete (either finished: true or stable notDelivered)
            logger.info(f"Successfully retrieved completed results for test {test_id_field}")
            self.update_audit_results(page_id, results['data'])
            
            # Clean up tracking for this test
            del self._test_tracking[test_id_field]

        except Exception as e:
            logger.error(f"Error getting test results for {test_id_field}: {e}")
            # Update error status
            error_properties = {
                "Audit Status": {"select": {"name": "Report Error"}}
            }
            self.notion.update_audit_fields(page_id, error_properties)
            self._append_error_log(page_id, "GlockApps Failed")
    
    def update_audit_results(self, page_id: str, results: Dict[str, Any]):
        """Update Notion with GlockApps test results"""
        try:
            # Extract relevant data from results based on the actual GlockApps API response structure
            # The response contains 'inboxes' array with placement information - nested under 'result' key
            inboxes = results.get("result", {}).get("inboxes", [])
            
            # Get stats from the response (new structure) - stats are nested under 'result' key
            stats = results.get("result", {}).get("stats", {})
            
            # Use stats if available, otherwise fall back to inboxes calculation
            if stats:
                # Use the stats directly from GlockApps response
                inbox_percentage = stats.get("inboxRate", 0)
                spam_percentage = stats.get("spamRate", 0)
                promotions_percentage = stats.get("otherRate", 0)
                spam_rate = stats.get("spamRate", 0)
                not_delivered_rate = stats.get("notDeliveredRate", 0)
                
                logger.info(f"Using stats from GlockApps: Inbox={inbox_percentage}%, Spam={spam_percentage}%, Other={promotions_percentage}%, NotDelivered={not_delivered_rate}%")
            else:
                # Fallback to calculating from inboxes array
                total_inboxes = len(inboxes)
                if total_inboxes > 0:
                    inbox_count = sum(1 for inbox in inboxes if inbox.get("iType") == "Inbox")
                    spam_count = sum(1 for inbox in inboxes if inbox.get("iType") == "Spam")
                    promotions_count = sum(1 for inbox in inboxes if inbox.get("iType") == "Promotions")
                    
                    inbox_percentage = (inbox_count / total_inboxes) * 100
                    spam_percentage = (spam_count / total_inboxes) * 100
                    promotions_percentage = (promotions_count / total_inboxes) * 100
                else:
                    inbox_percentage = spam_percentage = promotions_percentage = 0
                
                spam_rate = spam_percentage
                not_delivered_rate = 0
            
            update_properties = {
                "Audit Status": {"select": {"name": "GlockApps Completed"}},
                
                # Placement data from stats or calculated from inboxes
                "Inbox Placement %": {"number": round(inbox_percentage, 2)},
                "Spam Placement %": {"number": round(spam_percentage, 2)},
                "Promotions Placement %": {"number": round(promotions_percentage, 2)},
                
                # Use actual spam rate from stats
                "Spam Rate %": {"number": round(spam_rate, 2)},
                "Domain Reputation": {"select": {"name": "N/A"}},
                "IP Reputation": {"select": {"name": "N/A"}},
                
                # DNS data from GlockApps authentication results
                "SPF Status": {"select": {"name": self._get_authentication_status(results, "spfAuth")}},
                "DKIM Status": {"select": {"name": self._get_authentication_status(results, "dkimAuth")}},
                "DMARC Status": {"select": {"name": self._get_authentication_status(results, "dmarcAuth")}},
                "BIMI Status": {"select": {"name": self._get_authentication_status(results, "bimi")}},
                
                # Blacklist data (already populated from Step 1)
                # "IP Blacklist Status": {"rich_text": [{"text": {"content": blacklist_data.get("ip_status", "Clean")}}]},
                # "Domain Blacklist Status": {"rich_text": [{"text": {"content": blacklist_data.get("domain_status", "Clean")}}]},
                
                # Content data (set to 0 for now as not in current response)
                "Content Spam Score": {"number": 0},
                
                # Raw data
                "Raw JSON Output": {"rich_text": [{"text": {"content": str(results)[:2000]}}]},  # Limit to 2000 chars for Notion
                "Issues Found": {"rich_text": [{"text": {"content": self.generate_issues_summary(results)}}]}
            }
            
            # Log authentication statuses for debugging
            auth_result = results.get("result", {}).get("authenticationResult", {})
            if auth_result:
                logger.info(f"🔐 Authentication Results:")
                logger.info(f"   SPF: {auth_result.get('spfAuth', 'N/A')}")
                logger.info(f"   DKIM: {auth_result.get('dkimAuth', 'N/A')}")
                logger.info(f"   DMARC: {auth_result.get('dmarcAuth', 'N/A')}")
                logger.info(f"   BIMI: {auth_result.get('bimi', 'Not Configured')}")
            
            self.notion.update_audit_fields(page_id, update_properties)
            
            # Generate audit report body for Notion page
            # Get blacklist data from the current audit context
            blacklist_data = getattr(self, 'current_blacklist_data', {})
            if not blacklist_data:
                # Fallback: create basic blacklist data structure
                blacklist_data = {
                    "ip_status": "Data not available",
                    "domain_status": "Data not available"
                }
            
            # Generate structured Notion blocks for the report
            audit_blocks = self.report_generator.generate_audit_report_blocks(results, blacklist_data)
            
            # Debug logging to see what data is being used
            logger.info(f"🔍 Report Generation Debug:")
            logger.info(f"   GlockApps Results: {bool(results)}")
            logger.info(f"   Blacklist Data: {blacklist_data}")
            logger.info(f"   Report Blocks: {len(audit_blocks)} blocks")
            
            # Update Notion page with structured blocks
            self.notion.replace_page_content_blocks(page_id, audit_blocks)
            
            logger.info(f"✅ GlockApps completed! Status set to 'GlockApps Completed'")
            logger.info(f"🔄 System will now detect this status and run PostmarkApp automatically")
            
        except Exception as e:
            logger.error(f"Error updating audit results for page {page_id}: {e}")
    
    def _get_authentication_status(self, results: Dict[str, Any], auth_type: str) -> str:
        """Extract authentication status from GlockApps results"""
        try:
            # Navigate to authenticationResult in the nested structure
            auth_result = results.get("result", {}).get("authenticationResult", {})
            
            if not auth_result:
                return "N/A"
            
            # Get the specific authentication status
            if auth_type == "spfAuth":
                status = auth_result.get("spfAuth", "")
            elif auth_type == "dkimAuth":
                status = auth_result.get("dkimAuth", "")
            elif auth_type == "dmarcAuth":
                status = auth_result.get("dmarcAuth", "")
            elif auth_type == "bimi":
                status = auth_result.get("bimi", "")
            else:
                return "N/A"
            
            # Convert status to proper format
            if status == "pass":
                return "Pass"
            elif status == "fail":
                return "Fail"
            elif status == "neutral":
                return "Neutral"
            elif status == "softfail":
                return "Soft Fail"
            elif status == "none":
                return "None"
            elif status == "":
                return "Not Configured"
            else:
                return status.capitalize()
                
        except Exception as e:
            logger.error(f"Error extracting {auth_type} status: {e}")
            return "Error"
    
    def generate_issues_summary(self, results: Dict[str, Any]) -> str:
        """Generate a summary of issues found based on test results"""
        issues = []
        
        # Check placement issues based on stats (new structure) or inboxes array - stats are nested under 'result' key
        stats = results.get("result", {}).get("stats", {})
        if stats:
            # Use stats from GlockApps response
            inbox_percentage = stats.get("inboxRate", 0)
            spam_percentage = stats.get("spamRate", 0)
            not_delivered_rate = stats.get("notDeliveredRate", 0)
            
            if inbox_percentage < 80:
                issues.append(f"Low inbox placement rate ({inbox_percentage:.1f}%)")
            
            if spam_percentage > 20:
                issues.append(f"High spam placement rate ({spam_percentage:.1f}%)")
            
            if not_delivered_rate > 0:
                issues.append(f"Some emails not delivered ({not_delivered_rate:.1f}%)")
        else:
            # Fallback to inboxes array calculation - nested under 'result' key
            inboxes = results.get("result", {}).get("inboxes", [])
            if inboxes:
                total_inboxes = len(inboxes)
                inbox_count = sum(1 for inbox in inboxes if inbox.get("iType") == "Inbox")
                spam_count = sum(1 for inbox in inboxes if inbox.get("iType") == "Spam")
                
                inbox_percentage = (inbox_count / total_inboxes) * 100
                spam_percentage = (spam_count / total_inboxes) * 100
                
                if inbox_percentage < 80:
                    issues.append(f"Low inbox placement rate ({inbox_percentage:.1f}%)")
                
                if spam_percentage > 20:
                    issues.append(f"High spam placement rate ({spam_percentage:.1f}%)")
        
        # Check authentication issues
        auth_result = results.get("result", {}).get("authenticationResult", {})
        if auth_result:
            if auth_result.get("spfAuth") == "fail":
                issues.append("SPF authentication failed")
            if auth_result.get("dkimAuth") == "fail":
                issues.append("DKIM authentication failed")
            if auth_result.get("dmarcAuth") == "fail":
                issues.append("DMARC authentication failed")
            if auth_result.get("bimi") == "":
                issues.append("BIMI not configured")
        
        # Check if test is finished - nested under 'result' key
        if not results.get("result", {}).get("finished", False):
            issues.append("Test not yet completed")
        
        if not issues:
            return "No significant issues found"
        
        return "; ".join(issues)

    def _run_postmark_deliverability_check(self, page_id: str, glockapps_results: Dict[str, Any]):
        """Run PostmarkApp deliverability check after GlockApps completion"""
        try:
            # Get audit information from Notion
            audit_page = self.notion.client.pages.retrieve(page_id)
            props = audit_page.get("properties", {})
            
            # Extract audit ID
            audit_id = props.get("Audit ID", {}).get("title", [{}])[0].get("plain_text", "Unknown")
            
            # Extract domain and from email
            domain_relation = props.get("Domain", {}).get("relation", [])
            if not domain_relation:
                logger.warning("No domain relation found for PostmarkApp check")
                return
            
            domain_relation_id = domain_relation[0]["id"]
            domain_name = self.notion.get_domain_info(domain_relation_id)
            
            if not domain_name:
                logger.warning("Could not get domain name for PostmarkApp check")
                return
            
            # Create a sample email content for testing
            from_email = f"audit@{domain_name}"
            to_email = "test@example.com"  # Sample recipient
            subject = f"Email Audit Test - {domain_name}"
            
            # Create sample email content based on GlockApps results
            email_content = self._create_sample_email_content(domain_name, glockapps_results, audit_id)
            
            # Log the complete email content for debugging
            logger.info("=" * 60)
            logger.info("📧 EMAIL CONTENT FOR POSTMARKAPP SPAM SCORE CHECKING:")
            logger.info("=" * 60)
            logger.info(f"From: {from_email}")
            logger.info(f"To: {to_email}")
            logger.info(f"Subject: {subject}")
            logger.info("-" * 40)
            logger.info("Email Body:")
            logger.info(email_content)
            logger.info("=" * 60)
            
            # Run PostmarkApp deliverability check
            logger.info(f"Running PostmarkApp deliverability check for domain: {domain_name}")
            postmark_results = self.postmark_checker.check_email_deliverability(
                email_content, from_email, to_email, subject
            )
            
            if postmark_results.get("status") == "success":
                # Update Notion with PostmarkApp results
                self._update_notion_with_postmark_results(page_id, postmark_results)
                logger.info("✅ PostmarkApp deliverability check completed successfully")
            else:
                logger.warning(f"PostmarkApp check failed: {postmark_results.get('error')}")
                self._append_error_log(page_id, "PostmarkApp Failed")
                
                # PostmarkApp failed - use fallback values and continue to Postmaster immediately
                logger.warning(f"⚠️ PostmarkApp failed, using fallback values to continue workflow")
                
                # Create a fallback PostmarkApp result with default values
                fallback_postmark_results = {
                    "spam_score": 0,  # Default score
                    "deliverability_status": "Unknown (API Failed)",
                    "status": "completed_with_errors",
                    "error": f"PostmarkApp failed: {postmark_results.get('error')}"
                }
                
                # Continue with Postmaster by calling the same function that handles successful PostmarkApp results
                self._update_notion_with_postmark_results(page_id, fallback_postmark_results)
                
        except Exception as e:
            logger.error(f"Error in PostmarkApp deliverability check: {e}")
    
    def _create_sample_email_content(self, domain: str, glockapps_results: Dict[str, Any], audit_id: str) -> str:
        """Create complete email with headers for PostmarkApp testing"""
        from datetime import datetime
        import uuid
        
        # Extract test ID from GlockApps results
        test_id = glockapps_results.get("test_id", "Unknown")
        
        # Generate unique message ID
        message_id = f"<{uuid.uuid4()}@audit.{domain}>"
        
        # Get current timestamp
        current_time = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        
        # Create complete email with headers
        email_content = f"""From: audit@{domain}
To: test@example.com
Subject: Email Audit Test - {domain}
Date: {current_time}
Message-ID: {message_id}
Content-Type: text/plain; charset=UTF-8
MIME-Version: 1.0
X-Mailer: Email Audit System
X-Audit-ID: {audit_id}
X-GlockApps-Test-ID: {test_id}

Hello,

This is an automated email audit test for domain: {domain}

Audit ID: {audit_id}
GlockApps Test ID: {test_id}
From Email: audit@{domain}

This email is being sent as part of an email deliverability audit to test inbox placement, spam filtering, and overall email reputation.

Please do not reply to this email.

Best regards,
Email Audit System"""
        
        return email_content
    
    def _update_notion_with_postmark_results(self, page_id: str, postmark_results: Dict[str, Any]):
        """Update Notion with PostmarkApp deliverability results"""
        try:
            # Extract key metrics from PostmarkApp results
            spam_score = postmark_results.get("spam_score", 0)
            deliverability_status = postmark_results.get("deliverability_status", "Unknown")
            
            # Check if this is a fallback result due to API failure
            is_fallback = postmark_results.get("status") == "completed_with_errors"
            
            if is_fallback:
                logger.warning(f"⚠️ Using fallback PostmarkApp results due to API failure. Score: {spam_score}, Status: {deliverability_status}")
                logger.info(f"📝 Error details: {postmark_results.get('error', 'Unknown error')}")
            
            # First: mark as Postmark Completed and save score
            postmark_completed_properties = {
                "Audit Status": {"select": {"name": "Postmark Completed"}},
                "Content Spam Score": {"number": spam_score},
            }
            self.notion.update_audit_fields(page_id, postmark_completed_properties)

            # Run Google Postmaster scraper as an isolated step (separate process)
            try:
                audit_page = self.notion.client.pages.retrieve(page_id)
                props = audit_page.get("properties", {})
                domain_relation = props.get("Domain", {}).get("relation", [])
                if domain_relation:
                    domain_relation_id = domain_relation[0]["id"]
                    domain_name = self.notion.get_domain_info(domain_relation_id)
                else:
                    domain_name = None

                if domain_name:
                    logger.info(f"🚀 Running Postmaster scraper for domain: {domain_name}")
                    scraper_ok = self._run_postmaster_scraper(domain_name)
                    
                    # Generate final audit report after Postmaster completion
                    if scraper_ok:
                        logger.info("📊 Generating final audit report...")
                        final_blocks = self.report_generator.generate_final_audit_report_blocks(page_id, postmark_results, self.notion.client)
                        self.notion.replace_page_content_blocks(page_id, final_blocks)
                        logger.info("✅ Final audit report generated successfully")
                        
                        # Append screenshots AFTER report generation so they're not overwritten
                        logger.info("📸 Appending Postmaster screenshots to final report...")
                        self._append_postmaster_images_direct(page_id, domain_name)
                        logger.info("✅ Screenshots appended successfully")
                    else:
                        # Postmaster failed - log detailed error information
                        logger.error(f"❌ Postmaster scraper failed for domain: {domain_name}")
                        logger.error(f"❌ This audit will be completed WITHOUT Postmaster screenshots")
                        logger.error(f"❌ Common causes: Google login issues, network problems, browser crashes, Playwright errors")
                        logger.error(f"❌ Check postmaster_scraper.py logs for detailed error information")
                        
                        # Clean up any partial screenshots that might have been created
                        self._cleanup_domain_directory(domain_name)
                        
                        # Update Notion with Postmaster failure information
                        try:
                            self._append_error_log(page_id, "Postmaster Failed")
                            logger.info("✅ Updated Notion with Postmaster failure information")
                        except Exception as e:
                            logger.error(f"❌ Failed to update Notion with Postmaster failure: {e}")
                        
                        # Still generate the final report (without screenshots)
                        logger.info("📊 Generating final audit report (without Postmaster screenshots)...")
                        final_blocks = self.report_generator.generate_final_audit_report_blocks(page_id, postmark_results, self.notion.client)
                        self.notion.replace_page_content_blocks(page_id, final_blocks)
                        logger.info("✅ Final audit report generated (without Postmaster screenshots)")
                        
                        # Add note about missing screenshots in the report
                        try:
                            missing_screenshots_block = {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [{"type": "text", "text": {"content": "⚠️ Note: Postmaster screenshots could not be captured due to technical issues. The audit data above is complete, but visual dashboard information is unavailable."}}]
                                }
                            }
                            self.notion.client.blocks.children.append(block_id=page_id, children=[missing_screenshots_block])
                            logger.info("✅ Added missing screenshots note to report")
                        except Exception as e:
                            logger.error(f"❌ Failed to add missing screenshots note: {e}")
                else:
                    logger.warning("⚠️ Could not determine domain name for Postmaster scraper")
            except Exception as e:
                logger.warning(f"⚠️ Postmaster scraper step encountered an issue: {e}")

            # Finally: mark the entire audit as Completed
            self.notion.update_audit_fields(page_id, {"Audit Status": {"select": {"name": "Completed"}}})

            if is_fallback:
                logger.info(f"✅ Audit completed with fallback PostmarkApp values. Score: {spam_score}, Status: {deliverability_status}")
                logger.info(f"📊 Note: PostmarkApp API failed, but workflow continued with default values")
            else:
                logger.info(f"✅ Successfully completed ALL 3 steps! Audit marked as 'Completed'")
                logger.info(f"📊 PostmarkApp Score: {spam_score}, Status: {deliverability_status}")
            
        except Exception as e:
            logger.error(f"Error updating Notion with PostmarkApp results: {e}")

    def _run_postmaster_scraper(self, domain: str) -> bool:
        """Invoke the isolated Postmaster scraper script as a subprocess with the given domain.

        Returns True if the scraper exits with code 0, otherwise False.
        """
        try:
            python_exec = sys.executable or "python"
            cmd = [python_exec, "postmaster_scraper.py", "--domain", domain, "--headless"]
            logger.info(f"🧰 Executing: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("✅ Postmaster scraper completed successfully")
                return True
            else:
                # Enhanced error logging for Postmaster failures
                logger.error(f"❌ Postmaster scraper failed with exit code: {result.returncode}")
                logger.error(f"❌ Exit code {result.returncode} typically indicates:")
                if result.returncode == 1:
                    logger.error(f"   - Login failure (invalid credentials, 2FA required)")
                    logger.error(f"   - Network connectivity issues")
                    logger.error(f"   - Google service blocking/rate limiting")
                    logger.error(f"   - Playwright browser crashes")
                    logger.error(f"   - Screenshot capture failures")
                    logger.error(f"   - No graphs found (#K-h element missing or empty)")
                elif result.returncode == 2:
                    logger.error(f"   - Command line argument errors")
                elif result.returncode == 126:
                    logger.error(f"   - Permission denied or script not executable")
                elif result.returncode == 127:
                    logger.error(f"   - Script file not found")
                else:
                    logger.error(f"   - Unknown error (check postmaster_scraper.py for details)")
                
                # Log stdout/stderr for debugging
                if result.stdout:
                    logger.info(f"📤 STDOUT (last 1000 chars): {result.stdout[-1000:]}")
                    # Check for specific "No graphs found" error
                    if "No graphs found" in result.stdout:
                        logger.error(f"❌ SPECIFIC ERROR: Postmaster scraper stopped because no graphs were found")
                        logger.error(f"❌ This means the #K-h element is missing or empty on the dashboard")
                        logger.error(f"❌ The scraper correctly stopped instead of taking blank screenshots")
                if result.stderr:
                    logger.error(f"📥 STDERR (last 1000 chars): {result.stderr[-1000:]}")
                
                # Log command that failed for debugging
                logger.error(f"❌ Failed command: {' '.join(cmd)}")
                logger.error(f"❌ Working directory: {os.getcwd()}")
                logger.error(f"❌ Python executable: {python_exec}")
                
                return False
        except Exception as e:
            logger.error(f"❌ Failed to run Postmaster scraper: {e}")
            logger.error(f"❌ Exception type: {type(e).__name__}")
            logger.error(f"❌ This usually indicates:")
            logger.error(f"   - Python environment issues")
            logger.error(f"   - Missing dependencies (playwright not installed)")
            logger.error(f"   - File permission problems")
            logger.error(f"   - System resource limitations")
            return False

    def _append_postmaster_images_direct(self, page_id: str, domain: str) -> None:
        """Upload screenshots using Notion Direct Upload and append as image blocks."""
        try:
            base_output_dir = os.path.join(os.getcwd(), "screenshots", "postmaster")
            domain_dir = os.path.join(base_output_dir, domain)
            latest_manifest = os.path.join(domain_dir, "latest.json")
            if not os.path.exists(latest_manifest):
                logger.warning(f"⚠️ No Postmaster manifest found for {domain} at {latest_manifest}")
                return

            import json
            with open(latest_manifest, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            screenshots = manifest.get("screenshots", {})
            manifest_base_dir = manifest.get("base_dir", base_output_dir)

            # Order screenshots for consistent layout
            order = [
                ("spam_rate", "Spam Rate"),
                ("ip_reputation", "IP Reputation"),
                ("domain_reputation", "Domain Reputation"),
                ("authenticated_traffic", "Authenticated Traffic"),
            ]
            # Build absolute paths + captions
            image_paths: List[str] = []
            captions: List[str] = []
            for key, label in order:
                rel = screenshots.get(key)
                if not rel or rel == "failed" or str(rel).startswith("error:"):
                    continue
                abs_path = os.path.normpath(os.path.join(manifest_base_dir, rel))
                if os.path.exists(abs_path):
                    image_paths.append(abs_path)
                    captions.append(label)

            if not image_paths:
                logger.info("ℹ️ No local screenshots found to upload")
                # Still clean up the directory even if no images were found
                self._cleanup_domain_directory(domain)
                return

            # Append header first
            self.notion.client.blocks.children.append(block_id=page_id, children=[{
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Google Postmaster Screenshots"}}]
                }
            }])

            # Use direct upload helpers to embed as image blocks
            uploaded = self.notion.append_images_to_page(page_id, image_paths, captions)
            if uploaded:
                logger.info("✅ Uploaded and appended Postmaster screenshots to Notion page")
                # Clean up the domain directory after successful upload
                self._cleanup_domain_directory(domain)
            else:
                logger.warning("⚠️ Failed to upload screenshots to Notion page")
                # Don't clean up if upload failed - keep files for potential retry

        except Exception as e:
            logger.warning(f"⚠️ Could not append Postmaster screenshots: {e}")
    
    def _cleanup_domain_directory(self, domain: str) -> None:
        """Delete the domain directory and all its contents after screenshots are uploaded."""
        try:
            import shutil
            base_output_dir = os.path.join(os.getcwd(), "screenshots", "postmaster")
            domain_dir = os.path.join(base_output_dir, domain)
            
            if os.path.exists(domain_dir):
                shutil.rmtree(domain_dir)
                logger.info(f"🗑️ Successfully deleted domain directory: {domain_dir}")
            else:
                logger.info(f"ℹ️ Domain directory does not exist: {domain_dir}")
                
        except Exception as e:
            logger.warning(f"⚠️ Could not delete domain directory for {domain}: {e}")
            logger.warning(f"⚠️ Directory may need manual cleanup: {domain_dir}")
    


def main():
    """Main execution function"""
    if not all([NOTION_API_KEY, NOTION_AUDITS_DB_ID, GLOCKAPPS_API_KEY, GLOCKAPPS_FOLDER_ID]):
        logger.error("Missing required environment variables. Please check your .env file.")
        logger.error("Required variables: NOTION_API_KEY, NOTION_AUDITS_DB_ID, GLOCKAPPS_API_KEY, GLOCKAPPS_FOLDER_ID")
        return
    
    engine = EmailAuditEngine()
    
    logger.info("Starting Email Audit Engine...")
    logger.info("Press Ctrl+C to stop")
    
    # Test API connections first
    logger.info("Testing API connections...")
    
    # Test GlockApps API connection
    if not engine.glockapps.test_api_connection():
        logger.error("❌ GlockApps API connection failed. Please check your API key and try again.")
        logger.error("The system will continue but may fail when trying to create tests.")
    else:
        logger.info("✅ GlockApps API connection successful")
    
    # Test PostmarkApp API connection
    if not engine.postmark_checker.test_api_connection():
        logger.warning("⚠️ PostmarkApp API connection failed. Some features may be limited.")
    else:
        logger.info("✅ PostmarkApp API connection successful")
    
    try:
        while True:
            # Step 1: Process ONE running audit completely (if any)
            audit_processed = engine.process_running_audits()
            
            if audit_processed:
                # An audit was processed, wait a bit then check for completion
                logger.info("Waiting for audit to complete...")
                time.sleep(30)  # Wait 1 minute for status updates
                
                # Check for completed tests until this audit is done
                max_checks = 10  # Maximum 10 checks (5 minutes)
                max_time_seconds = 300  # Maximum 5 minutes total
                check_count = 0
                start_time = time.time()
                
                while check_count < max_checks:
                    # Check if we've exceeded maximum time
                    elapsed_time = time.time() - start_time
                    if elapsed_time > max_time_seconds:
                        logger.warning(f"⚠️ Maximum time limit ({max_time_seconds/60:.1f} minutes) reached for audit, moving to next audit cycle")
                        break
                    logger.info(f"Checking for test completion (attempt {check_count + 1}/{max_checks})...")
                    
                    # Check for fallback GlockApps audits that need to be moved to PostmarkApp
                    engine._handle_fallback_glockapps_audits()
                    
                    engine.check_completed_tests()
                    
                    # Check if we still have audits with "Awaiting Email Sending", "Emails Sent", "GlockApps Completed", OR "Postmark Completed" status
                    response = engine.notion.client.databases.query(
                        database_id=engine.notion.database_id,
                        filter={
                            "or": [
                                {"property": "Audit Status", "select": {"equals": "Awaiting Email Sending"}},
                                {"property": "Audit Status", "select": {"equals": "Emails Sent"}},
                                {"property": "Audit Status", "select": {"equals": "GlockApps Completed"}},
                                {"property": "Audit Status", "select": {"equals": "Postmark Completed"}}
                            ]
                        }
                    )
                    in_progress_audits = response.get("results", [])
                    
                    # Also check if any audit has been completed (Postmaster finished)
                    completed_response = engine.notion.client.databases.query(
                        database_id=engine.notion.database_id,
                        filter={"property": "Audit Status", "select": {"equals": "Completed"}}
                    )
                    completed_audits = completed_response.get("results", [])
                    
                    # Check for failed audits that should be skipped (excluding GlockApps and PostmarkApp failures since we handle them with fallback values)
                    failed_response = engine.notion.client.databases.query(
                        database_id=engine.notion.database_id,
                        filter={
                            "or": [
                                {"property": "Audit Status", "select": {"equals": "Blacklist Failed"}}
                            ]
                        }
                    )
                    failed_audits = failed_response.get("results", [])
                    
                    if failed_audits:
                        logger.warning(f"⚠️ Found {len(failed_audits)} failed audit(s), moving to next audit cycle")
                        break
                    
                    if not in_progress_audits:
                        logger.info("✅ All audits completed! Ready for next audit.")
                        break
                    
                    if completed_audits:
                        logger.info(f"🎉 Found {len(completed_audits)} completed audit(s)! Moving to next audit cycle.")
                        break
                    
                    logger.info(f"Still waiting for {len(in_progress_audits)} audit(s) to complete (Awaiting Email Sending/Emails Sent/GlockApps Completed/Postmark Completed)...")
                    time.sleep(30)  # Wait 1 minute between checks
                    check_count += 1
                    
                    if check_count >= max_checks:
                        logger.warning("⚠️ Maximum wait time reached, moving to next audit cycle")
                
            else:
                # No running audits found, check if there are any in progress
                logger.info("Checking if there are any audits in progress...")
                response = engine.notion.client.databases.query(
                    database_id=engine.notion.database_id,
                    filter={
                        "or": [
                            {"property": "Audit Status", "select": {"equals": "Awaiting Email Sending"}},
                            {"property": "Audit Status", "select": {"equals": "Emails Sent"}},
                            {"property": "Audit Status", "select": {"equals": "GlockApps Completed"}},
                            {"property": "Audit Status", "select": {"equals": "Postmark Completed"}}
                        ]
                    }
                )
                in_progress_audits = response.get("results", [])
                
                if in_progress_audits:
                    logger.info(f"Found {len(in_progress_audits)} audit(s) in progress (Awaiting Email Sending/Emails Sent/GlockApps Completed/Postmark Completed), checking for completion...")
                    
                    # Check for fallback GlockApps audits that need to be moved to PostmarkApp
                    engine._handle_fallback_glockapps_audits()
                    
                    engine.check_completed_tests()
                    time.sleep(30)  # Wait 1 minute before next check
                else:
                    # No running audits and no audits in progress, sleep longer
                    logger.info("💤 No running audits and no audits in progress. Sleeping for 1 minute before next scan...")
                    time.sleep(30)  # Sleep for 1 minute
            
    except KeyboardInterrupt:
        logger.info("Stopping Email Audit Engine...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.info("Stopping Email Audit Engine...")

if __name__ == "__main__":
    main()
    
    
    
    
    
