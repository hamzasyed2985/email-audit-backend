#!/usr/bin/env python3
"""
Google Postmaster Dashboard Scraper
Uses Playwright to automate login and data extraction from Google Postmaster Tools
"""
import os
import sys
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import argparse
import json

# Ensure Windows uses Selector loop (supports subprocess) BEFORE importing Playwright
if os.name == "nt":
    try:
        # Use Proactor loop on Windows to support subprocess creation (required by Playwright)
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from playwright.async_api import async_playwright, Page, Browser
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Redundant safeguard (kept in case module is imported after policy set elsewhere)
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

class PostmasterScraper:
    """Google Postmaster Dashboard Scraper using Playwright"""
    
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        
        # Login credentials
        self.email = os.getenv("GOOGLE_EMAIL", "")
        self.password = os.getenv("GOOGLE_PASSWORD", "")
        
        # URLs
        self.postmaster_url = "https://postmaster.google.com/u/0/managedomains"
        
        # Output directory for screenshots/manifests
        self.output_dir = os.path.join(os.getcwd(), "screenshots", "postmaster")
        
        # Dashboard URL templates (domain will be replaced)
        # Note: Google Postmaster may automatically change dr=120 to dr=7
        # Testing different date range values to see which ones work
        self.dashboard_urls = {
            "spam_rate": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=userReportedSpamRate&dr=7",
            "ip_reputation": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=ipReputation-Ugly%2CipReputation-Bad%2CipReputation-Good%2CipReputation-Beautiful&dr=7",
            "domain_reputation": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=domainReputation&dr=7",
            "authenticated_traffic": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=dkimRate%2CspfRate%2CdmarcRate&dr=7"
        }
        
        # Alternative date ranges to test (uncomment to try different values)
        self.alternative_date_ranges = {
            "30_days": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=userReportedSpamRate&dr=30",
            "60_days": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=userReportedSpamRate&dr=60",
            "90_days": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=userReportedSpamRate&dr=90",
            "120_days": "https://postmaster.google.com/u/0/dashboards#do={domain}&st=userReportedSpamRate&dr=120"
        }
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.start()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.stop()
        
    async def start(self):
        """Start the Playwright browser and create a new page"""
        try:
            self.playwright = await async_playwright().start()
            
            # Launch Chromium with optimized arguments
            logger.info("🌐 Launching Chromium browser...")
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-extensions',
                    '--no-first-run',
                    '--disable-default-apps',
                    '--disable-popup-blocking',
                    '--disable-notifications'
                ]
            )
            
            # Create new page
            self.page = await self.browser.new_page()
            
            # Set viewport
            await self.page.set_viewport_size({"width": 1280, "height": 720})
            
            # Set user agent to look more like a regular browser
            await self.page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            
            logger.info("✅ Playwright browser started successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to start Playwright: {e}")
            raise
            
    async def stop(self):
        """Stop the Playwright browser and cleanup"""
        try:
            if self.page:
                await self.page.close()
                logger.info("✅ Page closed")
                
            if self.browser:
                await self.browser.close()
                logger.info("✅ Browser closed")
                
            if self.playwright:
                await self.playwright.stop()
                logger.info("✅ Playwright stopped")
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
            
    async def login_to_postmaster(self) -> bool:
        """Login to Google Postmaster Dashboard"""
        try:
            logger.info("🌐 Navigating to Google Postmaster...")
            await self.page.goto(self.postmaster_url)
            
            # Wait for page to load
            await self.page.wait_for_load_state("networkidle")
            logger.info("✅ Page loaded successfully")
            
            # Wait for username input field to appear
            logger.info("🔍 Looking for username input field...")
            username_input = await self.page.wait_for_selector('input[type="email"], input[name="identifier"]', timeout=10000)
            
            if not username_input:
                logger.error("❌ Username input field not found")
                return False
                
            # Type username
            logger.info(f"📝 Typing username: {self.email}")
            await username_input.fill(self.email)
            
            # Find and click Next button
            logger.info("🔍 Looking for Next button...")
            next_button = await self.page.wait_for_selector(
                'button[jsname="LgbsSe"]:has-text("Next"), button:has-text("Next")',
                timeout=10000
            )
            
            if not next_button:
                logger.error("❌ Next button not found")
                return False
                
            # Click Next button
            logger.info("🖱️ Clicking Next button...")
            await next_button.click()
            
            # Wait for password screen to load - use a shorter timeout
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15000)
                logger.info("✅ Username submitted, waiting for password screen...")
            except Exception as e:
                logger.warning(f"⚠️ Network idle timeout, but continuing... {e}")
            
            # Wait for password input field
            logger.info("🔍 Looking for password input field...")
            password_input = await self.page.wait_for_selector('input[type="password"], input[name="password"]', timeout=10000)
            
            if not password_input:
                logger.error("❌ Password input field not found")
                return False
                
            # Type password
            logger.info("📝 Typing password...")
            await password_input.fill(self.password)
            
            # Find and click Next button for password
            logger.info("🔍 Looking for password Next button...")
            password_next_button = await self.page.wait_for_selector(
                'button[jsname="LgbsSe"]:has-text("Next"), button:has-text("Next")',
                timeout=10000
            )
            
            if not password_next_button:
                logger.error("❌ Password Next button not found")
                return False
                
            # Click Next button for password
            logger.info("🖱️ Clicking password Next button...")
            await password_next_button.click()
            
            # Wait for login to complete - use multiple strategies
            logger.info("⏳ Waiting for login to complete...")
            
            # Strategy 1: Wait for URL change
            try:
                await self.page.wait_for_function(
                    'window.location.href.includes("postmaster.google.com")',
                    timeout=20000
                )
                logger.info("✅ URL changed to Postmaster domain")
            except Exception as e:
                logger.warning(f"⚠️ URL change timeout: {e}")
            
            # Strategy 2: Wait for dashboard elements or specific content
            try:
                # Wait for either dashboard content or error messages
                await self.page.wait_for_selector(
                    '[data-testid="domain-list"], .domain-item, .error-message, [aria-label*="domain"]',
                    timeout=15000
                )
                logger.info("✅ Dashboard content detected")
            except Exception as e:
                logger.warning(f"⚠️ Dashboard content timeout: {e}")
            
            # Strategy 3: Simple wait for any page change
            try:
                await asyncio.sleep(3)  # Give the page time to load
                logger.info("✅ Waited for page to settle")
            except Exception as e:
                logger.warning(f"⚠️ Wait error: {e}")
            
            # Check if we're on the Postmaster dashboard
            current_url = self.page.url
            page_title = await self.page.title()
            
            logger.info(f"📍 Current URL: {current_url}")
            logger.info(f"📄 Page Title: {page_title}")
            
            # More flexible success detection
            success_indicators = [
                "postmaster.google.com" in current_url,
                "postmaster" in page_title.lower(),
                "domain" in page_title.lower(),
                "managedomains" in current_url
            ]
            
            if any(success_indicators):
                logger.info(f"✅ Successfully logged in! Current URL: {current_url}")
                return True
            else:
                # Check if there are any error messages
                try:
                    error_elements = await self.page.query_selector_all('.error-message, [role="alert"], .error')
                    if error_elements:
                        error_text = await error_elements[0].text_content()
                        logger.error(f"❌ Login error detected: {error_text}")
                        return False
                except Exception:
                    pass
                
                logger.warning(f"⚠️ Login status unclear. URL: {current_url}, Title: {page_title}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during login: {e}")
            return False
            
    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data from the Postmaster dashboard (placeholder for future implementation)"""
        try:
            logger.info("📊 Getting dashboard data...")
            
            # Wait for dashboard to load
            await self.page.wait_for_load_state("networkidle")
            
            # For now, just return basic info
            # This can be expanded later to extract specific data
            dashboard_data = {
                "timestamp": datetime.now().isoformat(),
                "current_url": self.page.url,
                "title": await self.page.title(),
                "status": "logged_in"
            }
            
            logger.info("✅ Dashboard data retrieved successfully")
            return dashboard_data
            
        except Exception as e:
            logger.error(f"❌ Error getting dashboard data: {e}")
            return {"error": str(e)}
            
    async def take_screenshot(self, filename: str = None) -> str:
        """Take a screenshot of the main content area on the current page"""
        try:
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"postmaster_screenshot_{timestamp}.png"
            
            # Wait for page content to load
            await asyncio.sleep(2)
            
            # First, check if the primary #K-h element exists and has meaningful content
            try:
                k_h_element = self.page.locator('#K-h')
                if await k_h_element.count() > 0:
                    # Check if element has content (not empty)
                    element_text = await k_h_element.text_content()
                    if element_text and len(element_text.strip()) > 10:  # Has meaningful content
                        logger.info(f"✅ Found #K-h element with content, taking screenshot")
                        await k_h_element.screenshot(path=filename)
                        logger.info(f"📸 #K-h element screenshot saved: {filename}")
                        return filename
                    else:
                        logger.error(f"❌ #K-h element found but has no meaningful content (length: {len(element_text.strip() if element_text else '0')})")
                        logger.error(f"❌ No graphs found - stopping scraper")
                        return ""  # Return empty string to indicate failure
                else:
                    logger.error(f"❌ #K-h element not found")
                    logger.error(f"❌ No graphs found - stopping scraper")
                    return ""  # Return empty string to indicate failure
            except Exception as e:
                logger.error(f"❌ Error checking #K-h element: {e}")
                logger.error(f"❌ No graphs found - stopping scraper")
                return ""  # Return empty string to indicate failure
            
        except Exception as e:
            logger.error(f"❌ Error taking screenshot: {e}")
            return ""
            
        except Exception as e:
            logger.error(f"❌ Error taking screenshot: {e}")
            return ""

    async def is_on_dashboard(self) -> bool:
        """Check if we're actually on the Postmaster dashboard"""
        try:
            current_url = self.page.url
            page_title = await self.page.title()
            
            # Check for dashboard indicators
            dashboard_indicators = [
                "postmaster.google.com" in current_url,
                "postmaster" in page_title.lower(),
                "domain" in page_title.lower(),
                "managedomains" in current_url
            ]
            
            # Also check for specific dashboard elements
            try:
                dashboard_elements = await self.page.query_selector_all(
                    '[data-testid="domain-list"], .domain-item, [aria-label*="domain"], .postmaster-content'
                )
                if dashboard_elements:
                    logger.info("✅ Dashboard elements found")
                    return True
            except Exception:
                pass
            
            return any(dashboard_indicators)
            
        except Exception as e:
            logger.error(f"❌ Error checking dashboard status: {e}")
            return False
            
    async def wait_for_dashboard_load(self, timeout: int = 30000) -> bool:
        """Wait for dashboard to fully load"""
        try:
            logger.info("⏳ Waiting for dashboard to load...")
            
            # Wait for any of these conditions
            start_time = datetime.now()
            
            while (datetime.now() - start_time).total_seconds() < timeout / 1000:
                if await self.is_on_dashboard():
                    logger.info("✅ Dashboard loaded successfully")
                    return True
                    
                # Wait a bit and check again
                await asyncio.sleep(1)
                
            logger.warning("⚠️ Dashboard load timeout")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error waiting for dashboard: {e}")
            return False

    async def debug_page_state(self):
        """Debug current page state for troubleshooting"""
        try:
            current_url = self.page.url
            page_title = await self.page.title()
            
            logger.info("🔍 === PAGE DEBUG INFO ===")
            logger.info(f"📍 Current URL: {current_url}")
            logger.info(f"📄 Page Title: {page_title}")
            
            # Check for common elements
            try:
                # Check for Google login elements
                google_elements = await self.page.query_selector_all('input[type="email"], input[type="password"]')
                logger.info(f"🔐 Google form elements found: {len(google_elements)}")
                
                # Check for Postmaster elements
                postmaster_elements = await self.page.query_selector_all('[data-testid="domain-list"], .domain-item')
                logger.info(f"📊 Postmaster elements found: {len(postmaster_elements)}")
                
                # Check for error messages
                error_elements = await self.page.query_selector_all('.error-message, [role="alert"], .error')
                if error_elements:
                    for i, elem in enumerate(error_elements[:3]):  # Show first 3 errors
                        try:
                            error_text = await elem.text_content()
                            logger.info(f"❌ Error {i+1}: {error_text}")
                        except Exception:
                            logger.info(f"❌ Error {i+1}: [Could not read text]")
                
            except Exception as e:
                logger.error(f"❌ Error during debug: {e}")
                
            logger.info("🔍 === END DEBUG INFO ===")
            
        except Exception as e:
            logger.error(f"❌ Debug function error: {e}")

    async def capture_dashboard_screenshots(self, domain: str) -> Dict[str, str]:
        """Navigate to each dashboard URL and capture screenshots"""
        try:
            logger.info(f"📊 Starting dashboard screenshots for domain: {domain}")
            
            screenshots = {}
            
            # Ensure domain directory exists
            try:
                domain_dir = os.path.join(self.output_dir, domain)
                os.makedirs(domain_dir, exist_ok=True)
            except Exception as e:
                logger.warning(f"⚠️ Could not create domain screenshot directory: {e}")
                domain_dir = os.getcwd()
            
            for dashboard_name, url_template in self.dashboard_urls.items():
                try:
                    # Construct the full URL for this domain
                    full_url = url_template.format(domain=domain)
                    logger.info(f"🌐 Navigating to {dashboard_name} dashboard: {full_url}")
                    
                    # Navigate to the dashboard
                    await self.page.goto(full_url)
                    
                    # Wait for the dashboard to load
                    try:
                        await self.page.wait_for_load_state("networkidle", timeout=15000)
                        logger.info(f"✅ {dashboard_name} dashboard loaded")
                    except Exception as e:
                        logger.warning(f"⚠️ Network idle timeout for {dashboard_name}, but continuing... {e}")
                    
                    # Additional wait for dashboard content
                    try:
                        await asyncio.sleep(3)  # Give charts and data time to load
                        logger.info(f"⏳ Waited for {dashboard_name} content to settle")
                    except Exception as e:
                        logger.warning(f"⚠️ Wait error for {dashboard_name}: {e}")
                    
                    # Extra wait specifically for graphs and charts to fully render
                    try:
                        await asyncio.sleep(3)  # Additional 3 seconds for graphs to fully load
                        logger.info(f"⏳ Extra wait for {dashboard_name} graphs to fully render")
                    except Exception as e:
                        logger.warning(f"⚠️ Extra wait error for {dashboard_name}: {e}")
                    
                    # Only change date range on the first page (spam_rate)
                    if dashboard_name == "spam_rate":
                        logger.info(f"🔍 Changing date range to 120 days on {dashboard_name} page...")
                        date_range_changed = await self.change_date_range_to_120_days(dashboard_name)
                        if date_range_changed:
                            logger.info(f"✅ Date range changed to 120 days on {dashboard_name}")
                        else:
                            logger.warning(f"⚠️ Failed to change date range on {dashboard_name}")
                    else:
                        logger.info(f"ℹ️ Skipping date range change for {dashboard_name} - should inherit from spam_rate page")
                    
                    # Take screenshot after date range change (or with default if change failed)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"postmaster_{dashboard_name}_{domain}_{timestamp}.png"
                    filepath = os.path.join(domain_dir, filename)
                    
                    # Log the current URL before taking screenshot
                    current_url = self.page.url
                    logger.info(f"📍 Taking screenshot of {dashboard_name} at URL: {current_url}")
                    
                    screenshot_path = await self.take_screenshot(filepath)
                    if screenshot_path:
                        # Store both absolute and relative (from output_dir) paths
                        try:
                            rel_path = os.path.relpath(screenshot_path, self.output_dir)
                        except Exception:
                            rel_path = screenshot_path
                        screenshots[dashboard_name] = rel_path
                        logger.info(f"📸 {dashboard_name} screenshot saved: {screenshot_path}")
                    else:
                        logger.error(f"❌ Failed to save {dashboard_name} screenshot - #K-h element not found or has no content")
                        logger.error(f"❌ Stopping scraper - no graphs found")
                        # Return early with error to stop the scraper
                        return {"error": "No graphs found - #K-h element missing or empty"}
                    
                    # Small delay between dashboards
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Error capturing {dashboard_name} dashboard: {e}")
                    screenshots[dashboard_name] = f"error: {str(e)}"
            
            logger.info(f"✅ Dashboard screenshots completed for {domain}")
            return screenshots
            
        except Exception as e:
            logger.error(f"❌ Error in dashboard screenshots: {e}")
            return {"error": str(e)}

    async def verify_date_range_change(self, dashboard_name: str) -> bool:
        """Verify that the date range was successfully changed to 120 days"""
        try:
            logger.info(f"🔍 Verifying date range change for {dashboard_name}...")
            
            # Wait a bit for the page to update
            await asyncio.sleep(2)
            
            # Look for indicators that the date range is now 120 days
            try:
                # Check if there's any text indicating 120 days
                page_content = await self.page.content()
                
                if "120 days" in page_content or "120 day" in page_content:
                    logger.info(f"✅ Date range successfully changed to 120 days for {dashboard_name}")
                    return True
                elif "7 days" in page_content or "7 day" in page_content:
                    logger.warning(f"⚠️ Date range still shows 7 days for {dashboard_name}")
                    return False
                else:
                    logger.info(f"ℹ️ Could not determine date range for {dashboard_name}, assuming change was successful")
                    return True
                    
            except Exception as e:
                logger.warning(f"⚠️ Could not verify date range for {dashboard_name}: {e}")
                return True  # Assume success if we can't verify
                
        except Exception as e:
            logger.error(f"❌ Error verifying date range for {dashboard_name}: {e}")
            return False

    async def change_date_range_to_120_days(self, dashboard_name: str) -> bool:
        """Change the date range to 120 days on the specified dashboard page"""
        try:
            logger.info(f"🔍 Looking for date range dropdown on {dashboard_name} page...")
            
            # Look specifically for the dropdown that contains "Last 7 days" text
            date_dropdown = None
            
            # Strategy 1: Look for the specific dropdown containing "Last 7 days"
            try:
                date_dropdown = await self.page.wait_for_selector(
                    'div[role="listbox"]:has(div:has-text("Last 7 days"))',
                    timeout=5000
                )
                logger.info(f"✅ Found date range dropdown containing 'Last 7 days'")
            except Exception:
                pass
            
            # Strategy 2: Look for the specific class combination that contains "Last 7 days"
            if not date_dropdown:
                try:
                    date_dropdown = await self.page.wait_for_selector(
                        'div.j-S-ah.j-i-u-am.w-aW-i-u.tk3N6e-b5.w-TzA9Ye-aR:has(div:has-text("Last 7 days"))',
                        timeout=5000
                    )
                    logger.info(f"✅ Found date range dropdown using specific class + text selector")
                except Exception:
                    pass
            
            # Strategy 3: Look for any listbox that has "Last 7 days" as a child
            if not date_dropdown:
                try:
                    date_dropdown = await self.page.wait_for_selector(
                        'div[role="listbox"] div[role="option"]:has-text("Last 7 days")',
                        timeout=5000
                    )
                    # If we found the option, get its parent listbox
                    if date_dropdown:
                        date_dropdown = await date_dropdown.query_selector('xpath=..')
                        logger.info(f"✅ Found date range dropdown using option text + parent selector")
                except Exception:
                    pass
            
            if date_dropdown:
                logger.info(f"✅ Found date range dropdown on {dashboard_name} page")
                
                # Click the dropdown to open it
                await date_dropdown.click()
                logger.info(f"🖱️ Clicked date range dropdown on {dashboard_name} page")
                
                # Wait for dropdown to expand
                await asyncio.sleep(1)
                
                # Click on "Last 120 days" option
                logger.info(f"🔍 Looking for 'Last 120 days' option...")
                try:
                    # Wait for the "Last 120 days" option to appear
                    last_120_days_option = await self.page.wait_for_selector(
                        'div[role="option"]:has-text("Last 120 days")',
                        timeout=5000
                    )
                    
                    if last_120_days_option:
                        logger.info(f"✅ Found 'Last 120 days' option on {dashboard_name} page")
                        
                        # Click on "Last 120 days"
                        await last_120_days_option.click()
                        logger.info(f"🖱️ Clicked 'Last 120 days' option on {dashboard_name} page")
                        
                        # Wait for the page to update with new data
                        logger.info(f"⏳ Waiting for {dashboard_name} page to update with 120 days data...")
                        await asyncio.sleep(5)  # Give more time for data to load
                        
                        # Verify that the date range was actually changed
                        date_range_changed = await self.verify_date_range_change(dashboard_name)
                        if date_range_changed:
                            logger.info(f"✅ Date range verified as 120 days for {dashboard_name}")
                            return True
                        else:
                            logger.warning(f"⚠️ Date range change verification failed for {dashboard_name}")
                            return False
                        
                    else:
                        logger.warning(f"⚠️ 'Last 120 days' option not found on {dashboard_name} page")
                        return False
                        
                except Exception as e:
                    logger.warning(f"⚠️ Could not click 'Last 120 days' on {dashboard_name} page: {e}")
                    return False
                
            else:
                logger.warning(f"⚠️ Date range dropdown containing 'Last 7 days' not found on {dashboard_name} page")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ Could not interact with date range dropdown on {dashboard_name} page: {e}")
            return False

    async def run_full_audit(self, domain: str) -> Dict[str, Any]:
        """Run the complete Postmaster audit for a specific domain"""
        try:
            logger.info(f"🚀 Starting full Postmaster audit for domain: {domain}")
            
            # Step 1: Login
            login_success = await self.login_to_postmaster()
            if not login_success:
                return {"status": "failed", "error": "Login failed", "domain": domain}
            
            # Step 2: Wait for dashboard
            dashboard_ready = await self.wait_for_dashboard_load(timeout=30000)
            if not dashboard_ready:
                logger.warning("⚠️ Dashboard didn't load properly, but continuing...")
            
            # Step 3: Capture dashboard screenshots
            dashboard_screenshots = await self.capture_dashboard_screenshots(domain)
            
            # Check if screenshots failed due to missing #K-h element
            if isinstance(dashboard_screenshots, dict) and dashboard_screenshots.get("error"):
                error_msg = dashboard_screenshots.get("error", "Unknown error")
                logger.error(f"❌ Dashboard screenshots failed: {error_msg}")
                logger.error(f"❌ Stopping scraper - no graphs found")
                return {
                    "status": "failed", 
                    "error": error_msg, 
                    "domain": domain,
                    "timestamp": datetime.now().isoformat()
                }
            
            # Write manifest for main process to consume
            manifest = {
                "domain": domain,
                "timestamp": datetime.now().isoformat(),
                "screenshots": dashboard_screenshots,
                "base_dir": self.output_dir
            }
            try:
                domain_dir = os.path.join(self.output_dir, domain)
                os.makedirs(domain_dir, exist_ok=True)
                timestamp_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                manifest_path = os.path.join(domain_dir, f"manifest_{timestamp_tag}.json")
                latest_path = os.path.join(domain_dir, "latest.json")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
                with open(latest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
                logger.info(f"🗂️ Manifest written: {manifest_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not write manifest: {e}")
                manifest_path = ""
            
            # Step 4: Compile results
            audit_results = {
                "status": "completed",
                "domain": domain,
                "login_success": login_success,
                "dashboard_ready": dashboard_ready,
                "screenshots": dashboard_screenshots,
                "timestamp": datetime.now().isoformat(),
                "manifest_path": manifest_path
            }
            
            logger.info(f"✅ Full audit completed for domain: {domain}")
            return audit_results
            
        except Exception as e:
            logger.error(f"❌ Full audit failed for domain {domain}: {e}")
            return {
                "status": "failed", 
                "error": str(e), 
                "domain": domain,
                "timestamp": datetime.now().isoformat()
            }

    async def run_multiple_domain_audits(self, domains: List[str]) -> Dict[str, Dict[str, Any]]:
        """Run Postmaster audits for multiple domains"""
        try:
            logger.info(f"🚀 Starting audits for {len(domains)} domains: {', '.join(domains)}")
            
            all_results = {}
            
            for domain in domains:
                logger.info(f"🎯 Processing domain: {domain}")
                
                # Run audit for this domain
                domain_result = await self.run_full_audit(domain)
                all_results[domain] = domain_result
                
                # Small delay between domains
                if domain != domains[-1]:  # Don't delay after the last domain
                    logger.info("⏳ Waiting 3 seconds before next domain...")
                    await asyncio.sleep(3)
            
            logger.info(f"✅ Completed audits for {len(domains)} domains")
            return all_results
            
        except Exception as e:
            logger.error(f"❌ Error in multiple domain audits: {e}")
            return {"error": str(e)}

    def get_dashboard_urls_for_domain(self, domain: str) -> Dict[str, str]:
        """Get the actual URLs for a specific domain"""
        return {
            dashboard_name: url_template.format(domain=domain)
            for dashboard_name, url_template in self.dashboard_urls.items()
        }

    async def test_network_connectivity(self) -> bool:
        """Test basic network connectivity to Google services"""
        try:
            logger.info("🌐 Testing network connectivity...")
            
            # Test 1: Basic Google connectivity
            try:
                logger.info("🔍 Testing connection to google.com...")
                await self.page.goto("https://google.com", timeout=10000)
                logger.info("✅ Successfully connected to google.com")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to connect to google.com: {e}")
                
                # Test 2: Try a different Google service
                try:
                    logger.info("🔍 Testing connection to gmail.com...")
                    await self.page.goto("https://gmail.com", timeout=10000)
                    logger.info("✅ Successfully connected to gmail.com")
                    return True
                except Exception as e2:
                    logger.error(f"❌ Failed to connect to gmail.com: {e2}")
                    
                    # Test 3: Try a non-Google site
                    try:
                        logger.info("🔍 Testing connection to example.com...")
                        await self.page.goto("https://example.com", timeout=10000)
                        logger.info("✅ Successfully connected to example.com")
                        logger.warning("⚠️ Can connect to other sites but not Google - possible Google blocking")
                        return False
                    except Exception as e3:
                        logger.error(f"❌ Failed to connect to example.com: {e3}")
                        logger.error("❌ Cannot connect to any sites - network connectivity issue")
                        return False
            
        except Exception as e:
            logger.error(f"❌ Error testing network connectivity: {e}")
            return False

    def provide_troubleshooting_steps(self):
        """Provide troubleshooting steps for connection issues"""
        logger.info("🔧 === TROUBLESHOOTING STEPS ===")
        logger.info("1. Check your internet connection")
        logger.info("2. Try accessing https://postmaster.google.com in your regular browser")
        logger.info("3. Check if you're behind a corporate firewall or VPN")
        logger.info("4. Try disabling any antivirus/firewall temporarily")
        logger.info("5. Check if Google is accessible from your location")
        logger.info("6. Try using a different network (mobile hotspot)")
        logger.info("7. Check if your ISP is blocking Google services")
        logger.info("🔧 === END TROUBLESHOOTING ===")

async def run_cli(domain: str, headless: bool) -> int:
    """Run scraper via CLI for a single domain and return exit code"""
    try:
        logger.info("🚀 Starting Google Postmaster Scraper (CLI mode)...")
        async with PostmasterScraper(headless=headless) as scraper:
            # Run audit
            results = await scraper.run_full_audit(domain)
            if results.get("status") == "completed":
                logger.info("🎉 Audit completed successfully in CLI mode")
                # Give asyncio transports a tick to settle to avoid Windows closed-pipe noise
                try:
                    await asyncio.sleep(0)
                except Exception:
                    pass
                return 0
            else:
                logger.error(f"❌ Audit failed: {results.get('error')}")
                # Try to capture an error screenshot
                try:
                    await scraper.take_screenshot("audit_failed_screenshot.png")
                except Exception:
                    pass
                try:
                    await asyncio.sleep(0)
                except Exception:
                    pass
                return 1
    except Exception as e:
        logger.error(f"❌ CLI execution error: {e}")
        return 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google Postmaster Scraper")
    parser.add_argument("--domain", help="Domain to audit (e.g., example.com)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    args = parser.parse_args()
    if args.domain:
        exit_code = asyncio.run(run_cli(args.domain, args.headless))
        raise SystemExit(exit_code)
    else:
        # Backward-compatible: default domain for manual testing if none provided
        logger.info("No --domain provided. Running in demo mode for 'nuadvisorypartners.com'")
        exit_code = asyncio.run(run_cli("nuadvisorypartners.com", args.headless))
        raise SystemExit(exit_code)
