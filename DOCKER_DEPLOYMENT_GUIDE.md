# Docker Deployment Guide for Railway/Render

**Last Updated**: January 19, 2026

This guide explains how to properly deploy the NIJA trading bot on Railway and Render using Docker.

---

## ✅ Correct Approach for Railway/Render

When deploying to Railway or Render, follow these best practices:

### 1. Use a Single Dockerfile

Your repository should contain **one Dockerfile** that the platform will build automatically.

**Current Dockerfile** (simplified for platform compatibility):
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "start.sh"]
```

### 2. Let the Platform Build It

- Railway and Render have their own build systems
- They will automatically detect your Dockerfile and build it
- No need for manual `docker build` commands

**Railway Configuration** (`railway.json`):
```json
{
  "build": {
    "builder": "DOCKERFILE"
  }
}
```

**Render Configuration** (`render.yaml`):
```yaml
services:
  - type: web
    env: docker
    dockerfilePath: ./Dockerfile
```

### 3. No Docker Commands Inside Your App

- Don't run `docker build` in your application code
- Don't run `docker-compose` commands
- Don't access `/run/docker.sock`

---

## ❌ What NOT to Do

### 1. Don't Use docker-compose.yml

Docker Compose is designed for **local multi-container development**, not for cloud platform deployments.

**Why it's removed:**
- Railway and Render don't support docker-compose
- Causes confusion about the deployment method
- Not needed when deploying a single service

### 2. Don't Build Docker Images in Your Code

Your application code should never execute Docker commands:
```python
# ❌ BAD - Don't do this
import subprocess
subprocess.run(["docker", "build", "-t", "myapp", "."])
```

### 3. Don't Access Docker Socket

Cloud platforms don't expose the Docker socket to containers:
```python
# ❌ BAD - Won't work on Railway/Render
import docker
client = docker.from_env()  # This will fail
```

---

## 🚀 Deployment Methods

### Railway

1. **Connect your GitHub repository** to Railway
2. **Railway automatically detects** the Dockerfile
3. **Configure environment variables** in the dashboard
4. **Deploy** - Railway builds and runs your container

**Configuration File**: `railway.json`
- Sets `builder: DOCKERFILE` to use Docker
- Defines start command: `bash start.sh`

### Render

1. **Create a new Web Service** and connect to GitHub
2. **Select "Docker"** as the environment
3. **Set dockerfile path** to `./Dockerfile`
4. **Configure environment variables** in the dashboard
5. **Deploy** - Render builds and runs your container

**Configuration File**: `render.yaml`
- Sets `env: docker`
- Defines `dockerfilePath: ./Dockerfile`
- Defines `dockerCommand: bash start.sh`

---

## 🏠 Local Development

For local development, you have two options:

### Option 1: Run Directly with Python (Recommended)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your credentials

# Run the bot
./start.sh
```

### Option 2: Run with Docker

```bash
# Build the image (BuildKit is enabled by default for better performance)
docker build -t nija-bot .

# Run the container
docker run -d \
  --name nija \
  --env-file .env \
  -p 5000:5000 \
  nija-bot

# View logs
docker logs -f nija

# Stop the container
docker stop nija
docker rm nija
```

**Note**: For local Docker development, you can build and run directly. However:
- Don't use docker-compose for simplicity
- Don't commit docker-compose.yml files
- Keep deployment approach consistent with production

---

## 🔧 Environment Variables

All configuration is done via environment variables, not config files in the container.

**Setting Environment Variables:**

| Platform | Method |
|----------|--------|
| **Railway** | Dashboard → Variables → Add Variable |
| **Render** | Dashboard → Environment → Add Environment Variable |
| **Local** | Create `.env` file in repository root |
| **Docker CLI** | Use `--env-file .env` or `-e KEY=value` flags |

**Required Variables:**
- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`
- `KRAKEN_MASTER_API_KEY` (if using Kraken)
- `KRAKEN_MASTER_API_SECRET` (if using Kraken)

See `.env.example` for a complete list.

---

## 📋 Dockerfile Best Practices

### Current Simplified Dockerfile

The Dockerfile has been simplified to follow cloud platform best practices:

**Before** (Complex):
- Multiple RUN commands for pip
- Manual package installations
- Build-time verification steps
- Cache-busting arguments
- Working directory `/usr/src/app`

**After** (Simple):
- Single `pip install -r requirements.txt`
- Platform handles all dependencies from requirements.txt
- Clean, minimal layers
- Standard working directory `/app`

### Why This Matters

1. **Faster Builds**: Fewer layers = faster builds on Railway/Render
2. **Better Caching**: requirements.txt is copied first, enabling layer caching
3. **Easier to Maintain**: Simple Dockerfile is easier to understand and update
4. **Platform Compatible**: Follows Railway and Render best practices

---

## 🔍 Troubleshooting

### Build Fails on Railway/Render

**Symptom**: Deployment fails during build phase

**Solutions**:
1. Check that `railway.json` has `"builder": "DOCKERFILE"`
2. Check that `render.yaml` has `env: docker`
3. Verify all dependencies are in `requirements.txt`
4. Check build logs for specific error messages

### Container Starts But Crashes

**Symptom**: Build succeeds but container exits immediately

**Solutions**:
1. Check application logs for Python errors
2. Verify environment variables are set correctly
3. Verify `start.sh` has executable permissions
4. Check that required files exist in the container

### Dependencies Missing

**Symptom**: Import errors or "module not found"

**Solutions**:
1. Verify package is listed in `requirements.txt`
2. Check package name spelling and version
3. Clear build cache and redeploy
4. Check that package is compatible with Python 3.11

---

## 📚 Additional Resources

- **Railway Documentation**: https://docs.railway.app/
- **Render Documentation**: https://render.com/docs
- **Docker Best Practices**: https://docs.docker.com/develop/dev-best-practices/
- **Environment Variables Guide**: `KRAKEN_ENV_VARS_REFERENCE.md`
- **Restart Guide**: `RESTART_DEPLOYMENT.md`

---

## 🎯 Quick Reference

**✅ DO:**
- Use single Dockerfile
- Let platform build automatically
- Configure via environment variables
- Keep Dockerfile simple
- Use `.dockerignore` to exclude unnecessary files

**❌ DON'T:**
- Use docker-compose.yml for cloud deployment
- Run docker commands in application code
- Access Docker socket
- Hardcode credentials in Dockerfile
- Include build artifacts in image

---

**Questions?** Check the troubleshooting section or review platform-specific documentation.
