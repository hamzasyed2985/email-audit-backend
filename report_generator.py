import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class ReportGenerator:
    """Handles generation of structured Notion report blocks"""
    
    def __init__(self):
        pass
    
    def _h1(self, text: str) -> Dict[str, Any]:
        """Create a heading_1 block"""
        return {
            "object": "block", 
            "type": "heading_1", 
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _h2(self, text: str) -> Dict[str, Any]:
        """Create a heading_2 block"""
        return {
            "object": "block", 
            "type": "heading_2", 
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _p(self, text: str) -> Dict[str, Any]:
        """Create a paragraph block"""
        return {
            "object": "block", 
            "type": "paragraph", 
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _bullet(self, text: str) -> Dict[str, Any]:
        """Create a bulleted list item block"""
        return {
            "object": "block", 
            "type": "bulleted_list_item", 
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    def _divider(self) -> Dict[str, Any]:
        """Create a divider block"""
        return {"object": "block", "type": "divider", "divider": {}}
    
    def generate_audit_report_blocks(self, glockapps_results: Dict[str, Any], blacklist_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate initial audit report as structured Notion blocks after GlockApps completion"""
        try:
            # Extract data from GlockApps results
            stats = glockapps_results.get("result", {}).get("stats", {})
            auth_result = glockapps_results.get("result", {}).get("authenticationResult", {})
            
            # Extract placement data
            inbox_percentage = stats.get("inboxRate", 0)
            spam_percentage = stats.get("spamRate", 0)
            promotions_percentage = stats.get("otherRate", 0)
            not_delivered_rate = stats.get("notDeliveredRate", 0)
            
            # Extract authentication data
            spf_status = auth_result.get("spfAuth", "unknown")
            dkim_status = auth_result.get("dkimAuth", "unknown")
            dmarc_status = auth_result.get("dmarcAuth", "unknown")
            
            # Extract blacklist data
            ip_blacklist_status = blacklist_data.get("ip_status", "Clean")
            domain_blacklist_status = blacklist_data.get("domain_status", "Clean")
            
            blocks: List[Dict[str, Any]] = []
            
            # Executive Summary
            blocks.append(self._h1("Executive Summary"))
            blocks.append(self._p("(This section is for Mr. Dill's manual input. He will write a high-level summary of the findings and the most critical recommendations for the client here.)"))
            blocks.append(self._divider())
            
            # Discovery
            blocks.append(self._h1("Discovery"))
            blocks.append(self._h2("Client Goals"))
            blocks.append(self._p("(Manual Entry: Note the client's stated objectives, e.g., 'Improve IPR for marketing emails.')"))
            blocks.append(self._h2("Current Infrastructure"))
            blocks.append(self._p("(Manual Entry: Note the client's ESP, sending tools, etc., e.g., 'Sales' Apollo+SendGrid.')"))
            blocks.append(self._h2("Email Volume and Frequency"))
            blocks.append(self._p("(Manual Entry: e.g., 'Sends 10k marketing emails per week.')"))
            blocks.append(self._divider())
            
            # Sending Health Analysis
            blocks.append(self._h1("Sending Health Analysis"))
            blocks.append(self._h2("Inbox Placement Rate (IPR)"))
            blocks.append(self._p(f"Based on the GlockApps testing results, the current inbox placement rate stands at {inbox_percentage:.1f}%. This represents the percentage of emails that successfully reached recipients' primary inbox folders during the audit period."))
            blocks.append(self._h2("Spam Rate"))
            blocks.append(self._p(f"The spam placement rate is currently {spam_percentage:.1f}%, indicating the percentage of emails that were flagged as spam by various email providers. Additionally, {not_delivered_rate:.1f}% of emails were not delivered at all, which may indicate technical delivery issues or provider rejections."))
            blocks.append(self._h2("Bounce Rate"))
            blocks.append(self._p("(Mr. Dill can add the Bounce Rate table from his ESP here.)"))
            blocks.append(self._h2("IP and Domain Reputation"))
            blocks.append(self._p("(The Domain Reputation and IP Reputation properties will be populated automatically. Mr. Dill can add the reputation chart here.)"))
            blocks.append(self._h2("DNS Authentication"))
            blocks.append(self._bullet(f"SPF Status: {spf_status.upper()} - The Sender Policy Framework record is properly configured and authenticating successfully."))
            blocks.append(self._bullet(f"DKIM Status: {dkim_status.upper()} - DomainKeys Identified Mail authentication is working correctly."))
            blocks.append(self._bullet(f"DMARC Status: {dmarc_status.upper()} - Domain-based Message Authentication, Reporting & Conformance is properly implemented."))
            blocks.append(self._h2("Blacklists"))
            blocks.append(self._bullet(f"IP Blacklist Status: {ip_blacklist_status} - The sending IP address shows no significant blacklist detections."))
            blocks.append(self._bullet(f"Domain Blacklist Status: {domain_blacklist_status} - The domain name is not currently listed on major email blacklists."))
            blocks.append(self._h2("Email Structure"))
            blocks.append(self._p("(Manual Entry: Mr. Dill can add his analysis of the text-to-HTML ratio and tracking scripts here, as seen in the Fourthwall audit.)"))
            blocks.append(self._divider())
            
            # Resolution Plan
            blocks.append(self._h1("Resolution Plan"))
            blocks.append(self._p("(This is the most critical section for the client. Mr. Dill will manually write his actionable recommendations here, referencing the data above. For example: '1. Reduce the spam complaint rate by pausing cold outreach.' '2. Perform list maintenance and segment out unengaged users.')"))
            
            logger.info(f"Generated {len(blocks)} blocks for initial audit report")
            return blocks
            
        except Exception as e:
            logger.error(f"Error generating audit report blocks: {e}")
            return [self._p("Error generating audit report")]
    
    def generate_final_audit_report_blocks(self, page_id: str, postmark_results: Dict[str, Any], notion_client) -> List[Dict[str, Any]]:
        """Generate final audit report as structured Notion blocks, including Postmark results"""
        try:
            # Extract PostmarkApp data
            spam_score = postmark_results.get("spam_score", 0)
            deliverability_status = postmark_results.get("deliverability_status", "Unknown")
            
            # Get the current page to extract actual data from properties
            current_page = notion_client.pages.retrieve(page_id)
            props = current_page.get("properties", {})
            
            # Extract actual data from Notion properties
            inbox_percentage = props.get("Inbox Placement %", {}).get("number", 0)
            spam_percentage = props.get("Spam Placement %", {}).get("number", 0)
            promotions_percentage = props.get("Promotions Placement %", {}).get("number", 0)
            spam_rate = props.get("Spam Rate %", {}).get("number", 0)
            
            # Check if this is fallback data (GlockApps failed)
            test_id = props.get("GlockApps Test ID", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
            is_fallback = test_id.startswith("fallback_")
            
            # Extract authentication statuses
            spf_status = props.get("SPF Status", {}).get("select", {}).get("name", "Unknown")
            dkim_status = props.get("DKIM Status", {}).get("select", {}).get("name", "Unknown")
            dmarc_status = props.get("DMARC Status", {}).get("select", {}).get("name", "Unknown")
            
            # Extract blacklist statuses
            ip_blacklist_status = props.get("IP Blacklist Status", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "Data not available")
            domain_blacklist_status = props.get("Domain Blacklist Status", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "Data not available")
            
            # Check if blacklist checks failed (fallback values used)
            blacklist_failed = ("Fallback" in ip_blacklist_status or "Fallback" in domain_blacklist_status or 
                              "Error" in ip_blacklist_status or "Error" in domain_blacklist_status)
            
            blocks: List[Dict[str, Any]] = []
            
            # Executive Summary
            blocks.append(self._h1("Executive Summary"))
            blocks.append(self._p("(This section is for Mr. Dill's manual input. He will write a high-level summary of the findings and the most critical recommendations for the client here.)"))
            blocks.append(self._divider())
            
            # Discovery
            blocks.append(self._h1("Discovery"))
            blocks.append(self._h2("Client Goals"))
            blocks.append(self._p("(Manual Entry: Note the client's stated objectives, e.g., 'Improve IPR for marketing emails.')"))
            blocks.append(self._h2("Current Infrastructure"))
            blocks.append(self._p("(Manual Entry: Note the client's ESP, sending tools, etc., e.g., 'Sales' Apollo+SendGrid.')"))
            blocks.append(self._h2("Email Volume and Frequency"))
            blocks.append(self._p("(Manual Entry: e.g., 'Sends 10k marketing emails per week.')"))
            blocks.append(self._divider())
            
            # Sending Health Analysis
            blocks.append(self._h1("Sending Health Analysis"))
            blocks.append(self._h2("Inbox Placement Rate (IPR)"))
            if is_fallback:
                blocks.append(self._p(f"⚠️ NOTE: GlockApps testing failed during this audit. The system is using fallback values for analysis. The current inbox placement rate shows {inbox_percentage:.1f}%, but this represents fallback data due to GlockApps API failure."))
                blocks.append(self._p("Recommendation: Re-run this audit when GlockApps service is available for accurate deliverability metrics."))
            else:
                blocks.append(self._p(f"The automated email audit system has analyzed the domain's email deliverability performance. Based on the GlockApps testing results, the current inbox placement rate stands at {inbox_percentage:.1f}%. This represents the percentage of emails that successfully reached recipients' primary inbox folders during the audit period."))
            blocks.append(self._h2("Spam Rate"))
            if is_fallback:
                blocks.append(self._p(f"The spam placement rate shows {spam_percentage:.1f}% based on fallback data. ⚠️ NOTE: This represents fallback values due to GlockApps API failure and should not be considered accurate for decision-making."))
            else:
                blocks.append(self._p(f"The spam placement rate is currently {spam_percentage:.1f}%, indicating the percentage of emails that were flagged as spam by various email providers. The overall spam rate from the audit is {spam_rate:.1f}%."))
            blocks.append(self._h2("Bounce Rate"))
            blocks.append(self._p("(Mr. Dill can add the Bounce Rate table from his ESP here.)"))
            blocks.append(self._h2("IP and Domain Reputation"))
            blocks.append(self._p("(The Domain Reputation and IP Reputation properties will be populated automatically. Mr. Dill can add the reputation chart here.)"))
            blocks.append(self._h2("DNS Authentication"))
            if is_fallback:
                blocks.append(self._p("⚠️ NOTE: DNS authentication data is based on fallback values due to GlockApps API failure. These results may not reflect the actual current DNS configuration."))
            blocks.append(self._bullet(f"SPF Status: {spf_status.upper()} - The Sender Policy Framework record is properly configured and authenticating successfully."))
            blocks.append(self._bullet(f"DKIM Status: {dkim_status.upper()} - DomainKeys Identified Mail authentication is working correctly."))
            blocks.append(self._bullet(f"DMARC Status: {dmarc_status.upper()} - Domain-based Message Authentication, Reporting & Conformance is properly implemented."))
            blocks.append(self._h2("Blacklists"))
            if blacklist_failed:
                blocks.append(self._p("⚠️ NOTE: Blacklist data may be based on fallback values if the blacklist checker failed during this audit."))
            blocks.append(self._bullet(f"IP Blacklist Status: {ip_blacklist_status} - The sending IP address shows no significant blacklist detections."))
            blocks.append(self._bullet(f"Domain Blacklist Status: {domain_blacklist_status} - The domain name is not currently listed on major email blacklists."))
            blocks.append(self._h2("Email Structure"))
            blocks.append(self._p("(Manual Entry: Mr. Dill can add his analysis of the text-to-HTML ratio and tracking scripts here, as seen in the Fourthwall audit.)"))
            blocks.append(self._h2("Content Spam Score"))
            blocks.append(self._p(f"The PostmarkApp SpamCheck analysis has evaluated the email content quality and deliverability. The current content spam score is {spam_score}, which indicates {deliverability_status} deliverability performance. This score reflects the overall quality and compliance of the email content with industry best practices."))
            blocks.append(self._divider())
            
            # Resolution Plan
            blocks.append(self._h1("Resolution Plan"))
            blocks.append(self._p("(This is the most critical section for the client. Mr. Dill will manually write his actionable recommendations here, referencing the data above. For example: '1. Reduce the spam complaint rate by pausing cold outreach.' '2. Perform list maintenance and segment out unengaged users.')"))
            
            logger.info(f"Generated {len(blocks)} blocks for final audit report")
            return blocks
            
        except Exception as e:
            logger.error(f"Error generating final audit report blocks: {e}")
            return [self._p("Error generating final audit report")]
