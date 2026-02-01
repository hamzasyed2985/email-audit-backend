import logging
import requests
import json
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class PostmarkChecker:
    """Handles PostmarkApp API operations for email deliverability checking"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.base_url = "https://spamcheck.postmarkapp.com"
        
        # If no API key provided, try to get from environment
        if not self.api_key:
            import os
            self.api_key = os.getenv("POSTMARK_API_KEY")
        
        if not self.api_key:
            logger.warning("No PostmarkApp API key provided. Some features may be limited.")
    
    def test_api_connection(self) -> bool:
        """Test PostmarkApp API connection"""
        logger.info("Testing PostmarkApp API connection...")
        
        try:
            # Test with a simple request to check connectivity
            response = requests.get(
                f"{self.base_url}/doc/",
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("✅ PostmarkApp API connection successful")
                return True
            else:
                logger.warning(f"⚠️ PostmarkApp API returned status {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ PostmarkApp API connection failed: {e}")
            return False
    
    def check_email_deliverability(self, email_content: str, from_email: str, to_email: str, subject: str = "Test Email") -> Dict[str, Any]:
        """
        Check email deliverability using PostmarkApp SpamCheck API
        
        Args:
            email_content: The complete email with headers and body
            from_email: Sender email address (for logging)
            to_email: Recipient email address (for logging)
            subject: Email subject line (for logging)
            
        Returns:
            Dictionary containing deliverability results
        """
        logger.info(f"Checking email deliverability via PostmarkApp for {from_email} → {to_email}")
        
        try:
            # Prepare the email data for PostmarkApp
            # email_content now contains the complete email with headers
            email_data = {
                "email": email_content,
                "options": "long"
            }
            
            # Make request to PostmarkApp SpamCheck API
            response = requests.post(
                f"{self.base_url}/filter",
                json=email_data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("✅ Successfully received PostmarkApp deliverability results")
                
                # Parse and structure the results
                parsed_result = self._parse_postmark_results(result, from_email, to_email, subject)
                


                
                return parsed_result
            else:
                logger.error(f"Failed to get PostmarkApp results: {response.status_code} - {response.text}")
                return {
                    "status": "error",
                    "error": f"API request failed: {response.status_code}",
                    "details": response.text
                }
                
        except Exception as e:
            logger.error(f"Error checking email deliverability: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def _parse_postmark_results(self, raw_result: Dict[str, Any], from_email: str, to_email: str, subject: str) -> Dict[str, Any]:
        """Parse PostmarkApp API response into structured format"""
        
        try:
            # Extract key information from PostmarkApp response
            # Handle different response structures
            score = 0
            if "score" in raw_result:
                score = float(raw_result.get("score", 0))
            elif "Score" in raw_result:
                score = float(raw_result.get("Score", 0))
            
            rules = raw_result.get("rules", []) or raw_result.get("Rules", [])
            report = raw_result.get("report", "") or raw_result.get("Report", "")
            
            # Determine deliverability status based on score
            if score < 5:
                deliverability_status = "Excellent"
            elif score < 10:
                deliverability_status = "Good"
            elif score < 15:
                deliverability_status = "Fair"
            else:
                deliverability_status = "Poor"
            
            # Extract specific rule violations
            rule_violations = []
            for rule in rules:
                rule_score = 0
                if "score" in rule:
                    rule_score = float(rule.get("score", 0))
                elif "Score" in rule:
                    rule_score = float(rule.get("Score", 0))
                
                if rule_score > 0:
                    rule_name = rule.get("description", "") or rule.get("Description", "") or rule.get("name", "") or "Unknown"
                    rule_details = rule.get("details", "") or rule.get("Details", "") or ""
                    
                    rule_violations.append({
                        "rule": rule_name,
                        "score": rule_score,
                        "details": rule_details
                    })
            
            # Structure the results
            parsed_result = {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "from_email": from_email,
                "to_email": to_email,
                "subject": subject,
                "spam_score": score,
                "deliverability_status": deliverability_status,
                "rule_violations": rule_violations,
                "report": report,
                "raw_result": raw_result
            }
            
            logger.info(f"Parsed PostmarkApp results: Score={score}, Status={deliverability_status}")
            return parsed_result
            
        except Exception as e:
            logger.error(f"Error parsing PostmarkApp results: {e}")
            return {
                "status": "error",
                "error": f"Failed to parse results: {str(e)}",
                "raw_result": raw_result
            }
    

    
    def get_deliverability_summary(self, results: Dict[str, Any]) -> str:
        """Generate a human-readable summary of deliverability results"""
        if results.get("status") != "success":
            return f"Error: {results.get('error', 'Unknown error')}"
        
        score = results.get("spam_score", 0)
        status = results.get("deliverability_status", "Unknown")
        violations = results.get("rule_violations", [])
        
        summary = f"Spam Score: {score} ({status})"
        
        if violations:
            summary += f"\nRule Violations: {len(violations)}"
            for violation in violations[:3]:  # Show first 3 violations
                summary += f"\n- {violation['rule']} (Score: {violation['score']})"
        
        return summary
