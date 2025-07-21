# Image Search API

A powerful FastAPI service that searches and fetches images by keywords using DuckDuckGo as the primary search engine and Bing as a fallback. Features automatic proxy rotation to handle rate limits. No external APIs required - uses custom scraping logic.

## Features

- **Keyword-Based Search**: Simply enter keywords to find relevant images
- **Dual Search Engines**: DuckDuckGo (primary) + Bing (fallback) for maximum results
- **Automatic Proxy Rotation**: Uses TypeGPT proxy list to handle rate limits
- **Smart Rate Limit Handling**: Automatically switches to proxies when rate limited
- **Custom Logic**: No external APIs - built with custom scraping algorithms
- **Multiple Formats**: Get images as binary data or base64 encoded JSON
- **Smart Fallback**: Automatically switches to Bing if DuckDuckGo fails
- **RESTful API**: Clean endpoints with automatic OpenAPI documentation

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the API:
```bash
python main.py
```

The API will be available at:
- **Main API**: http://localhost:8000/
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### 1. Search Images
`GET /search-images`

Search for images by keyword.

**Parameters:**
- `keyword` (required): Search keyword
- `max_results` (optional): Maximum results (1-50, default: 10)

**Example:**
```bash
curl "http://localhost:8000/search-images?keyword=nature&max_results=5"
```

**Response:**
```json
{
  "keyword": "nature",
  "total_results": 5,
  "search_engine": "DuckDuckGo",
  "results": [
    {
      "title": "Beautiful Nature Scene",
      "image": "https://example.com/image.jpg",
      "thumbnail": "https://example.com/thumb.jpg",
      "url": "https://example.com/page",
      "height": 800,
      "width": 1200,
      "source": "DuckDuckGo"
    }
  ]
}
```

### 2. Search and Fetch Image
`GET /search-and-fetch`

Search for images and immediately return the specified image.

**Parameters:**
- `keyword` (required): Search keyword
- `format` (optional): "binary" (default) or "base64"
- `index` (optional): Image index to fetch (default: 0)

**Examples:**
```bash
# Get first image as binary
curl "http://localhost:8000/search-and-fetch?keyword=sunset" -o sunset.jpg

# Get second image as base64
curl "http://localhost:8000/search-and-fetch?keyword=mountains&format=base64&index=1"
```

### 3. Fetch Direct Image
`GET /fetch-image`

Fetch an image from a direct URL.

**Parameters:**
- `url` (required): Image URL
- `format` (optional): "binary" (default) or "base64"

**Example:**
```bash
curl "http://localhost:8000/fetch-image?url=https://example.com/image.jpg" -o image.jpg
```

### 4. Health Check
`GET /health`

Check API status.

## Usage Examples

### Python
```python
import requests
import base64

# Search for images
response = requests.get("http://localhost:8000/search-images", params={
    "keyword": "cats",
    "max_results": 5
})

data = response.json()
print(f"Found {data['total_results']} images using {data['search_engine']}")

for result in data['results']:
    print(f"- {result['title']}")
    print(f"  Image: {result['image']}")
    print(f"  Size: {result['width']}x{result['height']}")

# Get first image
response = requests.get("http://localhost:8000/search-and-fetch", params={
    "keyword": "sunset"
})

if response.status_code == 200:
    with open("sunset.jpg", "wb") as f:
        f.write(response.content)
    print("Image saved!")

# Get image as base64
response = requests.get("http://localhost:8000/search-and-fetch", params={
    "keyword": "mountains",
    "format": "base64"
})

data = response.json()
image_data = base64.b64decode(data['image_data'])
with open("mountains.jpg", "wb") as f:
    f.write(image_data)
```

### JavaScript
```javascript
// Search for images
async function searchImages(keyword) {
    const response = await fetch(`http://localhost:8000/search-images?keyword=${keyword}&max_results=5`);
    const data = await response.json();
    
    console.log(`Found ${data.total_results} images using ${data.search_engine}`);
    return data.results;
}

// Get image as base64 and display
async function displayImage(keyword) {
    const response = await fetch(`http://localhost:8000/search-and-fetch?keyword=${keyword}&format=base64`);
    const data = await response.json();
    
    const img = document.createElement('img');
    img.src = `data:image/jpeg;base64,${data.image_data}`;
    document.body.appendChild(img);
}

// Usage
searchImages('nature').then(results => {
    results.forEach(result => {
        console.log(`${result.title}: ${result.image}`);
    });
});

displayImage('sunset');
```

### cURL Examples
```bash
# Search for cat images
curl "http://localhost:8000/search-images?keyword=cats&max_results=3"

# Download first sunset image
curl "http://localhost:8000/search-and-fetch?keyword=sunset" -o sunset.jpg

# Get mountain image as base64
curl "http://localhost:8000/search-and-fetch?keyword=mountains&format=base64"

# Fetch specific image URL
curl "http://localhost:8000/fetch-image?url=https://example.com/image.jpg" -o downloaded.jpg

# Health check
curl "http://localhost:8000/health"
```

## How It Works

### Search Engine Priority
1. **DuckDuckGo (Primary)**: Uses VQD token extraction and official image search API
2. **Bing (Fallback)**: Custom scraping logic when DuckDuckGo fails

### DuckDuckGo Integration
- Extracts VQD tokens using multiple regex patterns
- Fallback token generation when extraction fails
- Handles pagination for more results
- Respects rate limits with delays

### Bing Fallback
- Scrapes Bing Images search results
- Parses JSON data from script tags
- Falls back to img tag parsing if needed
- Filters out small images and icons

### Smart Features
- **Automatic Fallback**: Seamlessly switches between search engines
- **URL Normalization**: Fixes protocol and formatting issues
- **Duplicate Prevention**: Caches URLs to avoid duplicates
- **Error Handling**: Comprehensive error handling and logging
- **Rate Limiting**: Respectful delays between requests

## Response Headers

When fetching images, useful headers are included:
- `X-Search-Keyword`: Original search keyword
- `X-Image-URL`: Source image URL
- `X-Search-Engine`: Which search engine was used
- `X-Image-Title`: Image title/description

## Error Handling

The API provides detailed error messages:
- `400`: Bad request or fetch failure
- `404`: No images found or invalid index
- `500`: Internal server error

## Performance Tips

- Use reasonable `max_results` values (10-20) for better performance
- The API automatically handles rate limiting
- Binary format is faster than base64 for large images
- First search may be slower due to VQD token extraction

## Limitations

- Search engines may rate limit if too many requests are made quickly
- Some images may not be accessible due to CORS or server restrictions
- VQD tokens may occasionally fail, triggering fallback methods
- Bing fallback may have fewer results than DuckDuckGo

## Development

To run in development mode:
```bash
python main.py
```

The server will automatically reload on code changes.

## License

This project is for educational and research purposes. Please respect the terms of service of search engines and be mindful of rate limiting.