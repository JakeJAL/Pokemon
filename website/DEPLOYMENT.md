# Deployment Guide

## Container Issues Fixed

### 1. EasyOCR Model Downloads
- **Problem**: EasyOCR downloads ~500MB models on first run
- **Solution**: Pre-download models during Docker build (see Dockerfile line 21)

### 2. OpenCV System Dependencies
- **Problem**: OpenCV needs system libraries not in base Python images
- **Solution**: Install required packages (libgl1-mesa-glx, libglib2.0-0, etc.) in Dockerfile

### 3. File System Paths
- **Problem**: Relative paths to all_cards.json and CSV files may break
- **Solution**: Volume mounts in docker-compose.yml

### 4. ChromaDB Persistence
- **Problem**: Vector database data lost on container restart
- **Solution**: Volume mount for /app/chroma_db directory

## Quick Start

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

### Docker Deployment
```bash
# Build and run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Manual Docker Build
```bash
# Build image
docker build -t pokemon-scanner .

# Run container
docker run -p 5000:5000 \
  -v $(pwd)/chroma_db:/app/chroma_db \
  -v $(pwd)/pokemon_cards_database.csv:/app/pokemon_cards_database.csv \
  -v $(pwd)/all_cards.json:/app/all_cards.json \
  --env-file .env \
  pokemon-scanner
```

## Production Considerations

### 1. Image Size
- Current image: ~2GB (includes EasyOCR models)
- Consider multi-stage builds if size is critical

### 2. Memory Requirements
- EasyOCR + OpenCV: ~1-2GB RAM minimum
- Recommend: 4GB RAM for production

### 3. GPU Support (Optional)
For faster OCR, add GPU support:
```dockerfile
# Use CUDA base image
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Install Python 3.11
RUN apt-get update && apt-get install -y python3.11 python3-pip

# Install PyTorch with CUDA
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

### 4. Environment Variables
Required in .env file:
```
API_KEY=your_openai_api_key
ENDPOINT=https://openrouter.ai/api/v1
OPENAI_API_KEY=your_key
OPENROUTER_API_KEY=your_key
```

### 5. Health Checks
Add to docker-compose.yml:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5000/"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## Cloud Deployment

### AWS ECS/Fargate
- Use at least 2GB memory task definition
- Mount EFS for ChromaDB persistence
- Use Application Load Balancer

### Google Cloud Run
- Set memory to 4GB
- Mount Cloud Storage bucket for data
- May need to increase timeout for OCR processing

### Azure Container Instances
- Use 4GB memory configuration
- Mount Azure Files for persistence
- Consider Azure Container Apps for auto-scaling

## Troubleshooting

### Issue: "libGL.so.1: cannot open shared object file"
**Solution**: System dependencies missing. Rebuild with Dockerfile provided.

### Issue: EasyOCR downloading models at runtime
**Solution**: Models should be pre-downloaded during build. Check Dockerfile line 21.

### Issue: ChromaDB data lost on restart
**Solution**: Ensure volume mount is configured in docker-compose.yml

### Issue: Out of memory errors
**Solution**: Increase container memory to at least 4GB

### Issue: Slow OCR processing
**Solution**: Consider GPU support or use smaller EasyOCR models
