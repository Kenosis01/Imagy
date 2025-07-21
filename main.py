from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
import requests
import os
import base64
from urllib.parse import urljoin, urlparse, quote, unquote
from bs4 import BeautifulSoup
import io
from typing import List, Optional
from pydantic import BaseModel, HttpUrl
import uvicorn
import json
import random
import time
from itertools import islice
import re
import threading
from datetime import datetime, timedelta

# Pydantic models
class ImageResult(BaseModel):
    title: str
    image: str
    thumbnail: str
    url: str
    height: int
    width: int
    source: str

class ImageResponse(BaseModel):
    image_data: str
    size: int
    source_url: str
    image_url: Optional[str] = None

class SearchImagesResponse(BaseModel):
    keyword: str
    total_results: int
    results: List[ImageResult]
    search_engine: str

class HealthResponse(BaseModel):
    status: str
    message: str

# Initialize FastAPI app
app = FastAPI(
    title="Image Search API",
    description="Search and fetch images using DuckDuckGo (primary) and Bing (fallback) with proxy support",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_proxy_index = 0
        self.failed_proxies = set()
        self.last_fetch_time = None
        self.fetch_lock = threading.Lock()
        self.load_proxies()
    
    def load_proxies(self):
        """Load proxies from the TypeGPT proxy list"""
        try:
            print("Loading proxies from TypeGPT...")
            response = requests.get("https://proxies.typegpt.net/ips.txt", timeout=10)
            response.raise_for_status()
            
            proxy_lines = response.text.strip().split('\n')
            self.proxies = []
            
            for line in proxy_lines:
                line = line.strip()
                if line and line.startswith('http://'):
                    self.proxies.append(line)
            
            print(f"Loaded {len(self.proxies)} proxies")
            random.shuffle(self.proxies)  # Randomize order
            
        except Exception as e:
            print(f"Failed to load proxies: {e}")
            self.proxies = []
    
    def get_proxy(self):
        """Get the current proxy"""
        if not self.proxies:
            return None
        
        # Remove failed proxies from the list
        if len(self.failed_proxies) > len(self.proxies) * 0.8:  # If 80% failed, reload
            print("Too many failed proxies, reloading...")
            self.failed_proxies.clear()
            self.load_proxies()
        
        # Find next working proxy
        attempts = 0
        while attempts < len(self.proxies):
            proxy = self.proxies[self.current_proxy_index]
            
            if proxy not in self.failed_proxies:
                return proxy
            
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
            attempts += 1
        
        # All proxies failed, reload
        print("All proxies failed, reloading...")
        self.failed_proxies.clear()
        self.load_proxies()
        return self.proxies[0] if self.proxies else None
    
    def mark_proxy_failed(self, proxy):
        """Mark a proxy as failed"""
        if proxy:
            self.failed_proxies.add(proxy)
            print(f"Marked proxy as failed: {proxy[:50]}...")
    
    def rotate_proxy(self):
        """Rotate to the next proxy"""
        if self.proxies:
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)

class ImageSearchAPI:
    def __init__(self):
        self.proxy_manager = ProxyManager()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
        self.timeout = 15
        self.rate_limit_count = 0
        self.last_request_time = datetime.now()
    
    def _make_request(self, method, url, **kwargs):
        """Make a request with proxy rotation on rate limits"""
        max_retries = 3
        current_proxy = None
        
        for attempt in range(max_retries):
            try:
                # Check if we need to use a proxy
                if self.rate_limit_count > 2:  # Use proxy after 2 rate limits
                    current_proxy = self.proxy_manager.get_proxy()
                    if current_proxy:
                        kwargs['proxies'] = {
                            'http': current_proxy,
                            'https': current_proxy
                        }
                        print(f"Using proxy: {current_proxy[:50]}...")
                
                # Make the request
                if method.upper() == 'GET':
                    response = self.session.get(url, **kwargs)
                elif method.upper() == 'POST':
                    response = self.session.post(url, **kwargs)
                else:
                    response = self.session.request(method, url, **kwargs)
                
                # Check for rate limiting
                if response.status_code in [429, 403, 503]:
                    self.rate_limit_count += 1
                    print(f"Rate limited (status {response.status_code}), count: {self.rate_limit_count}")
                    
                    if current_proxy:
                        self.proxy_manager.mark_proxy_failed(current_proxy)
                    
                    if attempt < max_retries - 1:
                        self.proxy_manager.rotate_proxy()
                        time.sleep(random.uniform(2, 5))  # Random delay
                        continue
                
                # Success - reset rate limit count
                if response.status_code == 200:
                    self.rate_limit_count = max(0, self.rate_limit_count - 1)
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.ProxyError as e:
                print(f"Proxy error: {e}")
                if current_proxy:
                    self.proxy_manager.mark_proxy_failed(current_proxy)
                self.proxy_manager.rotate_proxy()
                
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise
                
            except requests.exceptions.RequestException as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    self.rate_limit_count += 1
                    if current_proxy:
                        self.proxy_manager.mark_proxy_failed(current_proxy)
                    
                    if attempt < max_retries - 1:
                        self.proxy_manager.rotate_proxy()
                        time.sleep(random.uniform(3, 7))
                        continue
                
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise
        
        raise Exception(f"Failed to make request after {max_retries} attempts")
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL"""
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif not url.startswith(("http://", "https://")):
            url = "https://" + url
        return url
    
    def _extract_vqd(self, content: bytes, keywords: str) -> str:
        """Extract VQD token from DuckDuckGo response"""
        content_str = content.decode('utf-8', errors='ignore')
        
        patterns = [
            r'vqd="([^"]+)"',
            r"vqd='([^']+)'",
            r'vqd=([^&\s]+)',
            r'"vqd":"([^"]+)"',
            r"'vqd':'([^']+)'",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content_str)
            if match:
                return match.group(1)
        
        # Fallback VQD generation
        import hashlib
        timestamp = str(int(time.time()))
        hash_input = f"{keywords}{timestamp}".encode()
        hash_value = hashlib.md5(hash_input).hexdigest()[:10]
        return f"{timestamp}-{hash_value}-{len(keywords)}"
    
    def _get_vqd(self, keywords: str) -> str:
        """Get VQD token for DuckDuckGo search"""
        try:
            response = self._make_request(
                "GET",
                "https://duckduckgo.com",
                params={"q": keywords},
                timeout=self.timeout
            )
            return self._extract_vqd(response.content, keywords)
        except Exception:
            # Fallback VQD generation
            import hashlib
            timestamp = str(int(time.time()))
            hash_input = f"{keywords}{timestamp}".encode()
            hash_value = hashlib.md5(hash_input).hexdigest()[:10]
            return f"{timestamp}-{hash_value}-{len(keywords)}"
    
    def search_duckduckgo_images(self, keywords: str, max_results: int = 10) -> List[ImageResult]:
        """Search images using DuckDuckGo"""
        try:
            print(f"Searching DuckDuckGo for: {keywords}")
            vqd = self._get_vqd(keywords)
            
            payload = {
                "l": "wt-wt",
                "o": "json",
                "q": keywords,
                "vqd": vqd,
                "f": "",
                "p": "1",
            }
            
            results = []
            cache = set()
            
            # Try multiple pages
            for page in [0, 100]:
                if len(results) >= max_results:
                    break
                
                payload["s"] = str(page)
                try:
                    response = self._make_request(
                        "GET",
                        "https://duckduckgo.com/i.js",
                        params=payload,
                        timeout=self.timeout
                    )
                    
                    data = response.json()
                    page_data = data.get("results", [])
                    
                    for row in page_data:
                        if len(results) >= max_results:
                            break
                        
                        image_url = row.get("image")
                        if image_url and image_url not in cache:
                            cache.add(image_url)
                            result = ImageResult(
                                title=row.get("title", ""),
                                image=self._normalize_url(image_url),
                                thumbnail=self._normalize_url(row.get("thumbnail", "")),
                                url=self._normalize_url(row.get("url", "")),
                                height=int(row.get("height", 0)),
                                width=int(row.get("width", 0)),
                                source=row.get("source", "DuckDuckGo")
                            )
                            results.append(result)
                    
                    time.sleep(0.5)  # Be respectful
                    
                except Exception as e:
                    print(f"Error fetching DuckDuckGo page {page}: {e}")
                    continue
            
            print(f"DuckDuckGo found {len(results)} images")
            return results
            
        except Exception as e:
            print(f"DuckDuckGo search failed: {e}")
            return []
    
    def search_bing_images(self, keywords: str, max_results: int = 10) -> List[ImageResult]:
        """Search images using Bing (fallback method)"""
        try:
            print(f"Searching Bing for: {keywords}")
            
            # Bing Images search URL
            search_url = "https://www.bing.com/images/search"
            params = {
                "q": keywords,
                "form": "HDRSC2",
                "first": "1",
                "count": str(min(max_results, 35))
            }
            
            # Update headers for Bing
            headers = self.session.headers.copy()
            headers.update({
                'Referer': 'https://www.bing.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8'
            })
            
            response = self._make_request(
                "GET",
                search_url,
                params=params,
                headers=headers,
                timeout=self.timeout
            )
            
            soup = BeautifulSoup(response.content, 'html.parser')
            results = []
            
            # Method 1: Look for JSON data in script tags
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and 'mediaurl' in script.string.lower():
                    try:
                        # Extract JSON-like data
                        script_content = script.string
                        
                        # Look for image data patterns
                        pattern = r'"murl":"([^"]+)".*?"turl":"([^"]+)".*?"t":"([^"]*)"'
                        matches = re.findall(pattern, script_content)
                        
                        for match in matches[:max_results]:
                            if len(results) >= max_results:
                                break
                            
                            image_url = match[0].replace('\\u0026', '&')
                            thumbnail_url = match[1].replace('\\u0026', '&')
                            title = match[2] or f"{keywords} image"
                            
                            result = ImageResult(
                                title=title,
                                image=self._normalize_url(image_url),
                                thumbnail=self._normalize_url(thumbnail_url),
                                url=search_url,
                                height=0,
                                width=0,
                                source="Bing"
                            )
                            results.append(result)
                        
                        if results:
                            break
                            
                    except Exception as e:
                        print(f"Error parsing Bing script: {e}")
                        continue
            
            # Method 2: Fallback to img tags if JSON parsing fails
            if not results:
                print("Trying Bing fallback method...")
                img_tags = soup.find_all('img', src=True)
                
                for img in img_tags[:max_results * 2]:  # Get more to filter
                    if len(results) >= max_results:
                        break
                    
                    src = img.get('src', '')
                    if not src or src.startswith('data:'):
                        continue
                    
                    # Skip small images and icons
                    if any(x in src.lower() for x in ['icon', 'logo', 'button', 'pixel', 'blank']):
                        continue
                    
                    # Skip very small images
                    width = img.get('width', '0')
                    height = img.get('height', '0')
                    if width.isdigit() and height.isdigit():
                        if int(width) < 100 or int(height) < 100:
                            continue
                    
                    alt_text = img.get('alt', f"{keywords} image")
                    
                    result = ImageResult(
                        title=alt_text,
                        image=self._normalize_url(src),
                        thumbnail=self._normalize_url(src),
                        url=search_url,
                        height=int(height) if height.isdigit() else 0,
                        width=int(width) if width.isdigit() else 0,
                        source="Bing (fallback)"
                    )
                    results.append(result)
            
            print(f"Bing found {len(results)} images")
            return results
            
        except Exception as e:
            print(f"Bing search failed: {e}")
            return []
    
    def search_images(self, keywords: str, max_results: int = 10) -> tuple[List[ImageResult], str]:
        """Search images using DuckDuckGo first, then Bing as fallback"""
        
        # Try DuckDuckGo first
        results = self.search_duckduckgo_images(keywords, max_results)
        
        if results:
            return results, "DuckDuckGo"
        
        # Fallback to Bing
        print("DuckDuckGo failed, trying Bing fallback...")
        results = self.search_bing_images(keywords, max_results)
        
        if results:
            return results, "Bing"
        
        return [], "None"
    
    def fetch_image_from_url(self, image_url: str):
        """Fetch image from URL and return image data"""
        try:
            response = self._make_request("GET", image_url, stream=True, timeout=30)
            
            content_type = response.headers.get('content-type', '')
            if not content_type.startswith('image/'):
                return None, f"URL does not point to an image. Content-Type: {content_type}"
            
            return response.content, None
            
        except Exception as e:
            return None, str(e)

# Initialize API
image_api = ImageSearchAPI()

@app.get("/")
async def root():
    """API documentation"""
    return {
        "message": "Image Search API",
        "version": "1.0.0",
        "description": "Search and fetch images using DuckDuckGo (primary) and Bing (fallback) with proxy support",
        "features": [
            "DuckDuckGo image search (primary)",
            "Bing image search (fallback)",
            "Automatic proxy rotation on rate limits",
            "TypeGPT proxy integration",
            "Keyword-based search",
            "Binary and base64 response formats"
        ],
        "endpoints": {
            "/search-images": "Search for images by keyword",
            "/search-and-fetch": "Search and return first image",
            "/fetch-image": "Fetch image from direct URL",
            "/health": "Health check"
        }
    }

@app.get("/search-images", response_model=SearchImagesResponse)
async def search_images(
    keyword: str = Query(..., description="Search keyword for images"),
    max_results: int = Query(10, ge=1, le=50, description="Maximum number of results")
):
    """Search for images by keyword"""
    try:
        results, search_engine = image_api.search_images(keyword, max_results)
        
        return SearchImagesResponse(
            keyword=keyword,
            total_results=len(results),
            results=results,
            search_engine=search_engine
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Search failed: {str(e)}")

@app.get("/search-and-fetch")
async def search_and_fetch_image(
    keyword: str = Query(..., description="Search keyword for images"),
    format: str = Query("binary", description="Response format: 'binary' or 'base64'"),
    index: int = Query(0, ge=0, description="Index of image to fetch")
):
    """Search for images and return the specified image"""
    try:
        results, search_engine = image_api.search_images(keyword, index + 5)
        
        if not results:
            raise HTTPException(status_code=404, detail=f"No images found for keyword: {keyword}")
        
        if index >= len(results):
            raise HTTPException(
                status_code=404, 
                detail=f"Image index {index} not found. Only {len(results)} results available."
            )
        
        selected_result = results[index]
        image_url = selected_result.image
        
        image_data, error = image_api.fetch_image_from_url(image_url)
        
        if error:
            raise HTTPException(status_code=400, detail=f"Failed to fetch image: {error}")
        
        if format.lower() == 'base64':
            encoded_image = base64.b64encode(image_data).decode('utf-8')
            return ImageResponse(
                image_data=encoded_image,
                size=len(image_data),
                source_url=f"search:{keyword}",
                image_url=image_url
            )
        else:
            # Determine media type
            parsed_url = urlparse(image_url)
            filename = os.path.basename(parsed_url.path).lower()
            
            if filename.endswith('.png'):
                media_type = 'image/png'
            elif filename.endswith('.gif'):
                media_type = 'image/gif'
            elif filename.endswith('.webp'):
                media_type = 'image/webp'
            else:
                media_type = 'image/jpeg'
            
            return StreamingResponse(
                io.BytesIO(image_data),
                media_type=media_type,
                headers={
                    "Content-Disposition": f"inline; filename={keyword.replace(' ', '_')}_image_{index}.jpg",
                    "X-Search-Keyword": keyword,
                    "X-Image-URL": image_url,
                    "X-Search-Engine": search_engine,
                    "X-Image-Title": selected_result.title
                }
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.get("/fetch-image")
async def fetch_image(
    url: HttpUrl = Query(..., description="Image URL to fetch"),
    format: str = Query("binary", description="Response format: 'binary' or 'base64'")
):
    """Fetch and return an image from a direct URL"""
    image_url = str(url)
    
    image_data, error = image_api.fetch_image_from_url(image_url)
    
    if error:
        raise HTTPException(status_code=400, detail=error)
    
    if format.lower() == 'base64':
        encoded_image = base64.b64encode(image_data).decode('utf-8')
        return ImageResponse(
            image_data=encoded_image,
            size=len(image_data),
            source_url=image_url
        )
    else:
        parsed_url = urlparse(image_url)
        filename = os.path.basename(parsed_url.path).lower()
        
        if filename.endswith('.png'):
            media_type = 'image/png'
        elif filename.endswith('.gif'):
            media_type = 'image/gif'
        elif filename.endswith('.webp'):
            media_type = 'image/webp'
        else:
            media_type = 'image/jpeg'
        
        return StreamingResponse(
            io.BytesIO(image_data),
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename=image{os.path.splitext(filename)[1] or '.jpg'}"}
        )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    proxy_count = len(image_api.proxy_manager.proxies)
    failed_count = len(image_api.proxy_manager.failed_proxies)
    
    return HealthResponse(
        status="healthy",
        message=f"Image Search API is running. Proxies: {proxy_count} total, {failed_count} failed, Rate limits: {image_api.rate_limit_count}"
    )

if __name__ == "__main__":
    print("Starting Image Search API with Proxy Support...")
    print("Features:")
    print("- DuckDuckGo image search (primary)")
    print("- Bing image search (fallback)")
    print("- Automatic proxy rotation on rate limits")
    print("- TypeGPT proxy integration")
    print("- Keyword-based search")
    print("- Binary and base64 response formats")
    print()
    print("API Documentation: http://localhost:8000/docs")
    print()
    print("Example usage:")
    print("- Search: http://localhost:8000/search-images?keyword=nature&max_results=5")
    print("- Get image: http://localhost:8000/search-and-fetch?keyword=sunset")
    print("- Health: http://localhost:8000/health")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=10000,
        reload=True
    )
