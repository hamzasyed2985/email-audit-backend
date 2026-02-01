import logging
import os
import mimetypes
from typing import List, Dict, Any, Optional, Tuple
from notion_client import Client
import requests

logger = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"


class NotionManager:
    """Handles all Notion database operations"""
    
    def __init__(self, client: Client, database_id: str, api_key: Optional[str] = None):
        self.client = client
        self.database_id = database_id
        # Notion REST token used for endpoints not yet in notion_client SDK (e.g., file uploads)
        self.api_key = api_key or os.getenv("NOTION_API_KEY", "")
    
    def get_running_audits(self) -> List[Dict[str, Any]]:
        """Get all audits with status 'Running'"""
        try:
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={"property": "Audit Status", "select": {"equals": "Running"}}
            )
            return response.get("results", [])
        except Exception as e:
            logger.error(f"Error querying Notion database: {e}")
            return []
    
    def update_audit_fields(self, page_id: str, properties: Dict[str, Any]) -> bool:
        """Update audit fields in Notion"""
        try:
            self.client.pages.update(page_id=page_id, properties=properties)
            logger.info(f"Successfully updated Notion page: {page_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating Notion page {page_id}: {e}")
            return False
    
    def get_domain_info(self, domain_relation_id: str) -> Optional[str]:
        """Get domain name from domain relation"""
        try:
            domain_page = self.client.pages.retrieve(page_id=domain_relation_id)
            domain_name = domain_page["properties"]["Domain Name"]["title"][0]["plain_text"]
            return domain_name
        except Exception as e:
            logger.error(f"Error getting domain info: {e}")
            return None
    
    def get_audit_page(self, page_id: str) -> Optional[Dict[str, Any]]:
        """Get audit page details"""
        try:
            return self.client.pages.retrieve(page_id=page_id)
        except Exception as e:
            logger.error(f"Error retrieving audit page {page_id}: {e}")
            return None
    
    def update_page_content(self, page_id: str, content: str) -> bool:
        """Update the page content/body with the audit report"""
        try:
            # Get existing blocks to clear them
            existing_blocks = self.client.blocks.children.list(block_id=page_id)
            
            # Delete existing blocks one by one
            for block in existing_blocks.get("results", []):
                try:
                    self.client.blocks.delete(block_id=block["id"])
                except Exception as e:
                    logger.warning(f"Could not delete block {block['id']}: {e}")
            
            # Split content into chunks of 2000 characters to respect Notion's limit
            max_chunk_size = 1900  # Leave some buffer
            content_chunks = []
            
            if len(content) <= max_chunk_size:
                content_chunks = [content]
            else:
                # Split by lines to avoid breaking in the middle of sections
                lines = content.split('\n')
                current_chunk = ""
                
                for line in lines:
                    if len(current_chunk) + len(line) + 1 <= max_chunk_size:
                        current_chunk += line + '\n'
                    else:
                        if current_chunk:
                            content_chunks.append(current_chunk.strip())
                        current_chunk = line + '\n'
                
                if current_chunk:
                    content_chunks.append(current_chunk.strip())
            
            # Create blocks for each chunk
            blocks = []
            for chunk in content_chunks:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": chunk
                                }
                            }
                        ]
                    }
                })
            
            # Add all blocks at once
            self.client.blocks.children.append(
                block_id=page_id,
                children=blocks
            )
            
            logger.info(f"Successfully updated page content for: {page_id} with {len(blocks)} blocks")
            return True
            
        except Exception as e:
            logger.error(f"Error updating page content for {page_id}: {e}")
            return False

    def replace_page_content_blocks(self, page_id: str, blocks: List[Dict[str, Any]]) -> bool:
        """Replace page content with provided Notion blocks (clears existing then appends)."""
        try:
            # Clear existing blocks
            existing_blocks = self.client.blocks.children.list(block_id=page_id)
            for block in existing_blocks.get("results", []):
                try:
                    self.client.blocks.delete(block_id=block["id"])
                except Exception as e:
                    logger.warning(f"Could not delete block {block['id']}: {e}")

            if not blocks:
                return True

            # Append new blocks
            self.client.blocks.children.append(block_id=page_id, children=blocks)
            logger.info(f"Replaced page content for {page_id} with {len(blocks)} blocks")
            return True
        except Exception as e:
            logger.error(f"Error replacing page content blocks for {page_id}: {e}")
            return False

    def append_blocks(self, page_id: str, blocks: List[Dict[str, Any]]) -> bool:
        """Append blocks to the page without clearing existing content."""
        try:
            if not blocks:
                return True
            self.client.blocks.children.append(block_id=page_id, children=blocks)
            logger.info(f"Appended {len(blocks)} blocks to page {page_id}")
            return True
        except Exception as e:
            logger.error(f"Error appending blocks to page {page_id}: {e}")
            return False

    # === Direct Upload helpers (Notion File Upload API) ===
    def _create_file_upload(self, file_name: str, content_type: str) -> Optional[Tuple[str, str]]:
        """Create a Notion File Upload object and return (file_upload_id, upload_url)."""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "accept": "application/json",
                "content-type": "application/json",
                "Notion-Version": NOTION_VERSION,
            }
            payload = {
                "filename": file_name,
                "content_type": content_type,
            }
            resp = requests.post("https://api.notion.com/v1/file_uploads", json=payload, headers=headers, timeout=30)
            if resp.status_code != 200:
                logger.error(f"File upload create failed: {resp.status_code} - {resp.text}")
                return None
            data = resp.json()
            return data.get("id"), data.get("upload_url")
        except Exception as e:
            logger.error(f"Error creating file upload: {e}")
            return None

    def _send_file_upload(self, file_upload_id: str, file_path: str, content_type: str) -> bool:
        """Send binary contents to the given Notion File Upload ID."""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Notion-Version": NOTION_VERSION,
            }
            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                files = {
                    "file": (file_name, f, content_type or "application/octet-stream"),
                }
                url = f"https://api.notion.com/v1/file_uploads/{file_upload_id}/send"
                resp = requests.post(url, headers=headers, files=files, timeout=120)
                if resp.status_code != 200:
                    logger.error(f"Send file upload failed: {resp.status_code} - {resp.text}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error sending file upload: {e}")
            return False

    def append_images_to_page(self, page_id: str, image_paths: List[str], captions: Optional[List[str]] = None) -> bool:
        """Upload local image files to Notion and append them as image blocks on the page.

        Returns True if at least one image block was appended.
        """
        try:
            if not image_paths:
                return False

            children: List[Dict[str, Any]] = []
            captions = captions or [""] * len(image_paths)

            for idx, img_path in enumerate(image_paths):
                if not os.path.exists(img_path):
                    logger.warning(f"Image not found: {img_path}")
                    continue

                file_name = os.path.basename(img_path)
                mime_type, _ = mimetypes.guess_type(img_path)
                content_type = mime_type or "image/png"

                upload_info = self._create_file_upload(file_name, content_type)
                if not upload_info:
                    continue
                file_upload_id, _ = upload_info

                if not self._send_file_upload(file_upload_id, img_path, content_type):
                    continue

                caption_text = captions[idx] if idx < len(captions) else ""
                children.append({
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "file_upload",
                        "file_upload": {"id": file_upload_id},
                        "caption": [{"type": "text", "text": {"content": caption_text}}] if caption_text else []
                    }
                })

            if not children:
                return False

            self.client.blocks.children.append(block_id=page_id, children=children)
            logger.info(f"Appended {len(children)} image block(s) to page {page_id}")
            return True
        except Exception as e:
            logger.error(f"Error appending images to page {page_id}: {e}")
            return False
