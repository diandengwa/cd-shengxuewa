# OPC Content Factory

OPC (One Person Company) Content Factory - Automated content generation pipeline for K12 education WeChat public account.

## Features

- **Automated Content Pipeline**: Collect → Mine → Generate → Review → Publish
- **Docker Support**: Full containerization for easy deployment
- **Health Checks**: Built-in health monitoring
- **GitHub Actions CI/CD**: Automated build and deployment
- **Multi-platform**: Support Windows (local) and Linux (server)

## Quick Start

### Prerequisites

- Python 3.10+
- Docker Desktop (optional, for containerization)
- Git

### Installation

1. Clone the repository:
```bash
git clone https://github.com/diandengwa/opc-agent-knowledge.git
cd opc-agent-knowledge
```

2. Run the setup script:
```bash
python scripts/setup.py
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys
```

### Usage

#### Local Development

```bash
# Run health check
python scripts/health_check.py

# Run content generation (dry run)
python scripts/opc_generate_v4.py --dry-run

# Deploy locally with Docker
python scripts/deploy.py deploy --local
```

#### Docker Deployment

```bash
# Build and start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

#### GitHub Actions Deployment

1. Set up secrets in GitHub repository:
   - `SERVER_HOST`: Server IP address
   - `SERVER_USER`: Server username
   - `SERVER_SSH_KEY`: SSH private key

2. Push to main branch to trigger deployment

## Project Structure

```
opc/
├── scripts/              # Python scripts
│   ├── config_loader.py  # Configuration management
│   ├── health_check.py   # Health check script
│   ├── deploy.py         # Deployment script
│   └── setup.py          # Setup script
├── knowledge-base/       # Knowledge base
├── drafts/              # Generated drafts
├── reviewed/            # Reviewed content
├── ready-to-publish/    # Ready to publish
├── raw-articles/        # Raw articles
├── logs/                # Logs
├── Dockerfile            # Docker image definition
├── docker-compose.yml    # Docker Compose configuration
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Configuration

Configuration is managed through `config.yaml` and environment variables.

### Environment Variables

- `OPC_ROOT`: Project root directory
- `DEEPSEEK_API_KEY`: DeepSeek API key
- `MPTEXT_API_KEY`: mptext API key
- `GITHUB_TOKEN`: GitHub token
- `LOG_LEVEL`: Log level (DEBUG, INFO, WARN, ERROR)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License
