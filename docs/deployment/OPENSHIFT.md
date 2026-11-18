# Docling Pipelines OpenShift Deployment Guide

Complete guide for deploying the Docling Pipelines project on OpenShift using the automated deployment script.

## Overview

This guide covers deploying Docling Pipelines on OpenShift by:
1. Creating a project namespace
2. Building the application from Git repository
3. Creating an ImageStream for the container image
4. Deploying the application with proper configuration
5. Exposing the service via OpenShift Route

## Prerequisites

### Required Tools
- **OpenShift CLI (`oc`)**: Version 4.10 or higher
- **Git**: For repository access
- **OpenShift Cluster**: Access to an OpenShift cluster with appropriate permissions

### Required Permissions
- Create projects/namespaces
- Create builds, deployments, services, and routes
- Create imagestreams

### Verify Prerequisites

```bash
# Check oc CLI installation
oc version

# Login to OpenShift cluster
oc login https://api.your-cluster.com:6443

# Verify login
oc whoami
```

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/docling-project/docling-pipelines.git
cd docling-pipelines
```

### 2. Configure Git Credentials for Private Repositories

If the repository is private, export the Git username and personal access token before starting the deployment script. The script uses these values to create the OpenShift secret [`docpipe-git-auth`](../../README.md) and attach it to the build source.

```bash
export GIT_USERNAME="your-git-username"
export GIT_TOKEN="your-personal-access-token"

# Optional: override the secret name created by the script
export GIT_SECRET_NAME="docpipe-git-auth"  # pragma: allowlist secret
```

Notes:
- Use an HTTPS repository URL, not SSH
- The personal access token must have permission to read the repository
- Avoid putting the token directly on the command line or committing it to shell history files

### 3. Run Deployment Script

```bash
# Deploy with default settings (project name: docpipe)
./scripts/deploy-openshift.sh

# Or specify custom project name and Git repository
./scripts/deploy-openshift.sh my-docpipe-project https://github.com/docling-project/docling-pipelines.git main
```

### 4. Monitor Deployment

```bash
# Watch build progress
oc logs -f bc/docpipe-app

# Watch pod status
oc get pods -w

# Check deployment status
oc get deployment docpipe-backend
```

### 5. Access the Application

```bash
# Get the route URL
oc get route docpipe-route -o jsonpath='{.spec.host}'

# Test the application
DOCPIPE_URL=$(oc get route docpipe-route -o jsonpath='{.spec.host}')
curl -k https://$DOCPIPE_URL/health
```

## Deployment Script Details

### Script Parameters

```bash
./scripts/deploy-openshift.sh [project-name] [git-repo-url] [git-branch]
```

**Parameters:**
- `project-name` (optional): OpenShift project name (default: `docpipe`)
- `git-repo-url` (optional): Git repository URL (default: `https://github.com/docling-project/docling-pipelines.git`)
- `git-branch` (optional): Git branch to deploy (default: `main`)

### What the Script Does

1. **Prerequisites Check**
   - Verifies `oc` CLI is installed
   - Confirms user is logged into OpenShift
   - Displays current user and cluster information

2. **Project Creation**
   - Creates new OpenShift project with specified name
   - Checks for existing project and prompts for confirmation
   - Sets project as current context

3. **Git Credentials Secret Creation**
   - Reads `GIT_USERNAME` and `GIT_TOKEN` from the environment
   - Creates or updates an OpenShift basic-auth secret for Git access
   - Attaches that secret to the build source for private repository checkout

4. **Application BuildConfig Creation**
   - Creates a Docker build from the Git repository
   - Uses [`docker/Dockerfile`](../../docker/Dockerfile) for the image build
   - Starts the build explicitly

5. **ImageStream Creation**
   - Creates an internal ImageStream for storing built container images
   - Configures local lookup policy

6. **Deployment Creation**
   - Creates an OpenShift `DeploymentConfig` with 2 replicas
   - Triggers rollout from the built ImageStream tag
   - Configures resource limits and health checks

7. **Service Creation**
   - Creates ClusterIP Service for backend pods

8. **Route Creation**
   - Creates edge-terminated TLS route
   - Enables automatic HTTP to HTTPS redirect
   - Exposes service externally

9. **Verification**
   - Monitors build completion
   - Verifies pod, service, and route creation
   - Displays deployment summary

## Manual Deployment Steps

If you prefer manual deployment or need to customize the process:

### 1. Create Project

```bash
oc new-project docpipe --display-name="Docling Pipelines" \
  --description="Docling Pipelines - Modular document processing framework"
```

### 2. Create Application from Git

```bash
oc new-app python:3.12~https://github.com/docling-project/docling-pipelines.git \
  --name=docpipe-app \
  --strategy=source \
  --context-dir=. \
  --env PYTHONPATH=/opt/app-root/src/src \
  --env PYTHONUNBUFFERED=1
```

### 3. Create ImageStream

```bash
cat <<EOF | oc apply -f -
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: docpipe-image
spec:
  lookupPolicy:
    local: true
EOF
```

### 4. Create BuildConfig

```bash
cat <<EOF | oc apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: docpipe-build
spec:
  output:
    to:
      kind: ImageStreamTag
      name: docpipe-image:latest
  source:
    type: Git
    git:
      uri: https://github.com/docling-project/docling-pipelines.git
      ref: main
  strategy:
    type: Source
    sourceStrategy:
      from:
        kind: ImageStreamTag
        namespace: openshift
        name: python:3.12
EOF
```

### 5. Create Deployment

```bash
cat <<EOF | oc apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: docpipe-backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: docpipe-app
  template:
    metadata:
      labels:
        app: docpipe-app
    spec:
      containers:
      - name: docpipe
        image: docpipe-image:latest
        ports:
        - containerPort: 8000
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
EOF
```

### 6. Create Service

```bash
oc expose deployment docpipe-backend --port=8000 --name=docpipe-service
```

### 7. Create Route

```bash
oc create route edge docpipe-route --service=docpipe-service --insecure-policy=Redirect
```

## Configuration

### Environment Variables

The deployment configures the following environment variables:

- `PYTHONPATH=/opt/app-root/src/src`: Ensures Python can find docpipe modules
- `PYTHONUNBUFFERED=1`: Enables real-time log output

### Resource Limits

Default resource configuration per pod:

| Resource | Request | Limit |
|----------|---------|-------|
| Memory   | 2Gi     | 4Gi   |
| CPU      | 1 core  | 2 cores |

### Health Checks

**Liveness Probe:**
- Endpoint: `/health`
- Initial Delay: 30 seconds
- Period: 10 seconds

**Readiness Probe:**
- Endpoint: `/health`
- Initial Delay: 10 seconds
- Period: 5 seconds

## Operations

### Scaling

```bash
# Scale to 3 replicas
oc scale deployment/docpipe-backend --replicas=3

# Check scaling status
oc get deployment docpipe-backend
```

### Viewing Logs

```bash
# View application logs
oc logs -f deployment/docpipe-backend

# View specific pod logs
oc logs -f <pod-name>

# View build logs
oc logs -f bc/docpipe-app
```

### Rebuilding

```bash
# Trigger new build from Git
oc start-build docpipe-app

# Follow build logs
oc logs -f bc/docpipe-app

# Check build status
oc get builds
```

### Updating Configuration

```bash
# Update environment variable
oc set env deployment/docpipe-backend NEW_VAR=value

# Update resource limits
oc set resources deployment/docpipe-backend \
  --requests=cpu=1500m,memory=3Gi \
  --limits=cpu=2500m,memory=5Gi

# Rollout restart
oc rollout restart deployment/docpipe-backend
```

### Rolling Updates

```bash
# Update image
oc set image deployment/docpipe-backend docpipe=docpipe-image:v2.0

# Check rollout status
oc rollout status deployment/docpipe-backend

# View rollout history
oc rollout history deployment/docpipe-backend

# Rollback to previous version
oc rollout undo deployment/docpipe-backend
```

## Monitoring

### Pod Status

```bash
# List all pods
oc get pods

# Watch pod status
oc get pods -w

# Describe pod for events
oc describe pod <pod-name>
```

### Resource Usage

```bash
# View resource usage
oc adm top pods

# View node resource usage
oc adm top nodes
```

### Events

```bash
# View recent events
oc get events --sort-by='.lastTimestamp'

# Watch events
oc get events -w
```

## Troubleshooting

### Build Failures

```bash
# Check build logs
oc logs -f bc/docpipe-app

# Describe build for errors
oc describe build <build-name>

# Check build config
oc describe bc/docpipe-app
```

### Pod Not Starting

```bash
# Check pod status
oc get pods

# Describe pod for events
oc describe pod <pod-name>

# Check pod logs
oc logs <pod-name>

# Check previous container logs (if crashed)
oc logs <pod-name> --previous
```

### Image Pull Errors

```bash
# Check imagestream
oc get imagestream docpipe-image

# Describe imagestream
oc describe imagestream docpipe-image

# Check image tags
oc get imagestreamtag
```

### Route Not Accessible

```bash
# Check route configuration
oc get route docpipe-route

# Describe route
oc describe route docpipe-route

# Check service endpoints
oc get endpoints docpipe-service

# Test from inside cluster
oc run test-pod --image=curlimages/curl -it --rm -- \
  curl http://docpipe-service:8000/health
```

### Network Issues

```bash
# Check service
oc get svc docpipe-service

# Check endpoints
oc get endpoints docpipe-service

# Test connectivity from debug pod
oc debug deployment/docpipe-backend
```

## Cleanup

### Remove All Resources

```bash
# Delete all resources in project
oc delete all -l app=docpipe-app

# Or delete entire project
oc delete project docpipe
```

### Selective Cleanup

```bash
# Delete deployment only
oc delete deployment docpipe-backend

# Delete service
oc delete svc docpipe-service

# Delete route
oc delete route docpipe-route

# Delete buildconfig
oc delete bc docpipe-build

# Delete imagestream
oc delete imagestream docpipe-image
```

## Advanced Configuration

### Custom Dockerfile Build

If you need to use a custom Dockerfile instead of S2I:

```bash
# Create BuildConfig with Docker strategy
cat <<EOF | oc apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: docpipe-docker-build
spec:
  output:
    to:
      kind: ImageStreamTag
      name: docpipe-image:latest
  source:
    type: Git
    git:
      uri: https://github.com/docling-project/docling-pipelines.git
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Dockerfile
EOF
```

### Persistent Storage

Add persistent volume for data storage:

```bash
# Create PVC
cat <<EOF | oc apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: docpipe-data
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
EOF

# Mount in deployment
oc set volume deployment/docpipe-backend \
  --add --name=data-volume \
  --type=persistentVolumeClaim \
  --claim-name=docpipe-data \
  --mount-path=/data
```

### ConfigMaps and Secrets

```bash
# Create ConfigMap
oc create configmap docpipe-config \
  --from-file=config.yaml

# Create Secret
oc create secret generic docpipe-secrets \
  --from-literal=api-key=your-secret-key

# Mount in deployment
oc set volume deployment/docpipe-backend \
  --add --name=config \
  --type=configmap \
  --configmap-name=docpipe-config \
  --mount-path=/config

oc set env deployment/docpipe-backend \
  --from=secret/docpipe-secrets
```

## Integration with CI/CD

### Webhook Triggers

The BuildConfig includes webhook triggers for automated builds:

```bash
# Get webhook URL
oc describe bc/docpipe-build | grep -A 1 "Webhook GitHub"

# Configure in GitHub repository settings:
# Settings > Webhooks > Add webhook
# Payload URL: <webhook-url>
# Content type: application/json
```

### Jenkins Integration

```bash
# Create Jenkins pipeline
cat <<EOF | oc apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: docpipe-pipeline
spec:
  strategy:
    type: JenkinsPipeline
    jenkinsPipelineStrategy:
      jenkinsfile: |
        pipeline {
          agent any
          stages {
            stage('Build') {
              steps {
                script {
                  openshift.withCluster() {
                    openshift.withProject('docpipe') {
                      openshift.startBuild('docpipe-build').logs('-f')
                    }
                  }
                }
              }
            }
            stage('Deploy') {
              steps {
                script {
                  openshift.withCluster() {
                    openshift.withProject('docpipe') {
                      openshift.selector('deployment', 'docpipe-backend').rollout().latest()
                    }
                  }
                }
              }
            }
          }
        }
EOF
```

## Best Practices

1. **Use Specific Image Tags**: Avoid using `latest` tag in production
2. **Set Resource Limits**: Always define resource requests and limits
3. **Enable Health Checks**: Configure liveness and readiness probes
4. **Use Secrets**: Store sensitive data in OpenShift Secrets
5. **Enable Monitoring**: Configure Prometheus metrics and alerts
6. **Implement Logging**: Use centralized logging (EFK stack)
7. **Regular Backups**: Backup persistent data and configurations
8. **Security Scanning**: Scan images for vulnerabilities
9. **Network Policies**: Implement network policies for security
10. **Documentation**: Keep deployment documentation up to date

## Support

For issues or questions:
- Check pod logs: `oc logs <pod-name>`
- Review events: `oc get events --sort-by='.lastTimestamp'`
- Consult main documentation: [README.md](../README.md)
- Review architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)
