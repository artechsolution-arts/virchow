# Virchow AWS ECS Fargate CloudFormation Deployment

This directory contains CloudFormation templates and scripts to deploy Virchow on AWS ECS Fargate.

## Configuration

All configuration parameters are stored in a single JSON file: `virchow_config.json`. This file contains all the parameters needed for the different CloudFormation stacks.

Example:
```json
{
  "VirchowNamespace": "virchow",
  "Environment": "production",
  "EFSName": "virchow-efs",
  "AWSRegion": "us-east-2",
  "VpcID": "YOUR_VPC_ID",
  "SubnetIDs": "YOUR_SUBNET_ID1,YOUR_SUBNET_ID2",
  "DomainName": "YOUR_DOMAIN e.g ecs.virchow.app",
  "ValidationMethod": "DNS",
  "HostedZoneId": ""
}
```

### Required Parameters

- `Environment`: Used to prefix all stack names during deployment. This is required.
- `VirchowNamespace`: Namespace for the Virchow deployment.
- `EFSName`: Name for the Elastic File System.
- `AWSRegion`: AWS region where resources will be deployed.
- `VpcID`: ID of the VPC where Virchow will be deployed.
- `SubnetIDs`: Comma-separated list of subnet IDs for deployment.
- `DomainName`: Domain name for the Virchow deployment.
- `ValidationMethod`: Method for domain validation (typically "DNS").
- [optional] `HostedZoneId`: Route 53 hosted zone ID (only if using Route 53 for DNS).

The deployment script automatically extracts the needed parameters for each CloudFormation template based on the parameter names defined in the templates.

## Deployment Order

The deployment follows this order:

1. Infrastructure stacks:
   - EFS
   - Cluster
   - ACM

2. Service stacks:
   - Postgres
   - Redis
   - Vespa Engine
   - Model Server (Indexing)
   - Model Server (Inference)
   - Backend API Server
   - Backend Background Server
   - Web Server
   - Nginx

## Usage

To deploy:
```bash
./deploy.sh
```

To uninstall:
```bash
./uninstall.sh
```
