#!/bin/bash
set -e

# Docpipe OpenShift Deployment Script
# Usage: ./deploy-openshift.sh [project-name] [git-repo-url]

PROJECT_NAME=${1:-docpipe}
GIT_REPO=${2:-https://github.com/docling-project/docling-pipelines.git}
GIT_BRANCH=${3:-main}
GIT_USERNAME=${GIT_USERNAME:-}
GIT_TOKEN=${GIT_TOKEN:-}
GIT_SECRET_NAME=${GIT_SECRET_NAME:-docpipe-git-auth}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

check_prerequisites() {
    log_step "Checking prerequisites..."

    # Check oc CLI
    if ! command -v oc &> /dev/null; then
        log_error "oc CLI not found. Please install OpenShift CLI."
        exit 1
    fi

    # Check if logged in
    if ! oc whoami &> /dev/null; then
        log_error "Not logged in to OpenShift. Please run 'oc login' first."
        exit 1
    fi

    log_info "Logged in as: $(oc whoami)"
    log_info "Current server: $(oc whoami --show-server)"
    log_info "Prerequisites check passed"
}

create_git_secret() {
    log_step "Creating Git credentials secret..."

    if [ -z "$GIT_USERNAME" ] || [ -z "$GIT_TOKEN" ]; then
        log_warn "GIT_USERNAME or GIT_TOKEN not set. Skipping Git secret creation."
        return 0
    fi

    oc create secret generic "$GIT_SECRET_NAME" \
        --from-literal=username="$GIT_USERNAME" \
        --from-literal=password="$GIT_TOKEN" \
        --type=kubernetes.io/basic-auth \
        --dry-run=client -o yaml | oc apply -f -

    log_info "Git credentials secret ready: $GIT_SECRET_NAME"
}

create_project() {
    log_step "Creating OpenShift project: $PROJECT_NAME"

    # Check if project exists
    if oc get project "$PROJECT_NAME" &> /dev/null; then
        log_warn "Project $PROJECT_NAME already exists"
        read -p "Do you want to use the existing project? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_error "Deployment cancelled"
            exit 1
        fi
    else
        oc new-project "$PROJECT_NAME" --display-name="Docpipe Pipeline" \
            --description="Docpipe - Modular data processing framework"
        log_info "Project created successfully"
    fi

    # Switch to project
    oc project "$PROJECT_NAME"
}

create_app_from_git() {
    log_step "Creating application from Git repository..."

    APP_NAME="docpipe-app"

    # Check if app already exists
    if oc get bc "$APP_NAME" &> /dev/null 2>&1 || oc get deployment "$APP_NAME" &> /dev/null 2>&1; then
        log_warn "Application $APP_NAME already exists"
        read -p "Do you want to delete and recreate it? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Deleting existing application..."
            oc delete bc,build,svc,route,dc,deployment,imagestream -l app="$APP_NAME" 2>/dev/null || true
        else
            log_info "Using existing application"
            return 0
        fi
    fi

    log_info "Creating new application from Git: $GIT_REPO"
    log_info "Branch: $GIT_BRANCH"

    # Create docker build config from repository Dockerfile.
    cat <<EOF | oc apply -f -
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: $APP_NAME
  namespace: $PROJECT_NAME
  labels:
    app: $APP_NAME
    component: backend
spec:
  output:
    to:
      kind: ImageStreamTag
      name: docpipe-image:latest
  source:
    type: Git
    git:
      uri: $GIT_REPO
      ref: $GIT_BRANCH
    contextDir: .
    sourceSecret:
      name: $GIT_SECRET_NAME
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: docker/Dockerfile
  triggers: []
EOF

    oc start-build "$APP_NAME"

    log_info "BuildConfig created successfully"
    log_info "Build started. You can monitor with: oc logs -f build/$(oc get builds --sort-by=.metadata.creationTimestamp -l buildconfig="$APP_NAME" -o name | tail -1 | cut -d'/' -f2)"
}

create_imagestream() {
    log_step "Creating ImageStream..."

    IMAGESTREAM_NAME="docpipe-image"

    # Check if imagestream exists
    if oc get imagestream "$IMAGESTREAM_NAME" &> /dev/null; then
        log_warn "ImageStream $IMAGESTREAM_NAME already exists"
        return 0
    fi

    # Create internal imagestream without external import source.
    cat <<EOF | oc apply -f -
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: $IMAGESTREAM_NAME
  namespace: $PROJECT_NAME
  labels:
    app: docpipe-app
spec:
  lookupPolicy:
    local: true
EOF

    log_info "ImageStream created successfully"
}


create_deployment() {
    log_step "Creating Deployment configuration..."

    DEPLOYMENT_NAME="docpipe-backend"

    # Check if deployment exists
    if oc get deployment "$DEPLOYMENT_NAME" &> /dev/null; then
        log_warn "Deployment $DEPLOYMENT_NAME already exists"
        return 0
    fi

    # Create deployment
    cat <<EOF | oc apply -f -
apiVersion: apps.openshift.io/v1
kind: DeploymentConfig
metadata:
  name: $DEPLOYMENT_NAME
  namespace: $PROJECT_NAME
  labels:
    app: docpipe-app
    component: backend
spec:
  replicas: 2
  selector:
    app: docpipe-app
    component: backend
  triggers:
  - type: ImageChange
    imageChangeParams:
      automatic: true
      containerNames:
      - docpipe
      from:
        kind: ImageStreamTag
        name: docpipe-image:latest
  - type: ConfigChange
  template:
    metadata:
      labels:
        app: docpipe-app
        component: backend
    spec:
      containers:
      - name: docpipe
        image: image-registry.openshift-image-registry.svc:5000/$PROJECT_NAME/docpipe-image:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8080
          protocol: TCP
        env:
        - name: PYTHONPATH
          value: /opt/app-root/src
        - name: PYTHONUNBUFFERED
          value: "1"
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
EOF

    log_info "Deployment created successfully"
}

create_service() {
    log_step "Creating Service..."

    SERVICE_NAME="docpipe-service"

    # Check if service exists
    if oc get service "$SERVICE_NAME" &> /dev/null; then
        log_warn "Service $SERVICE_NAME already exists"
        return 0
    fi

    # Create service
    cat <<EOF | oc apply -f -
apiVersion: v1
kind: Service
metadata:
  name: $SERVICE_NAME
  namespace: $PROJECT_NAME
  labels:
    app: docpipe-app
spec:
  selector:
    app: docpipe-app
    component: backend
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    protocol: TCP
  type: ClusterIP
EOF

    log_info "Service created successfully"
}

create_route() {
    log_step "Creating Route..."

    ROUTE_NAME="docpipe-route"

    # Check if route exists
    if oc get route "$ROUTE_NAME" &> /dev/null; then
        log_warn "Route $ROUTE_NAME already exists"
        return 0
    fi

    # Create route
    cat <<EOF | oc apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: $ROUTE_NAME
  namespace: $PROJECT_NAME
  labels:
    app: docpipe-app
spec:
  to:
    kind: Service
    name: docpipe-service
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
EOF

    log_info "Route created successfully"
}

wait_for_build() {
    log_step "Waiting for build to complete..."

    APP_NAME="docpipe-app"
    BUILD_NAME=""
    BUILD_STATUS=""
    MAX_ATTEMPTS=120
    ATTEMPT=1

    while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
        BUILD_NAME=$(oc get builds --sort-by=.metadata.creationTimestamp -l buildconfig="$APP_NAME" -o name 2>/dev/null | tail -1 | cut -d'/' -f2)

        if [ -z "$BUILD_NAME" ]; then
            log_info "Waiting for build to be created... ($ATTEMPT/$MAX_ATTEMPTS)"
            sleep 5
            ATTEMPT=$((ATTEMPT + 1))
            continue
        fi

        BUILD_STATUS=$(oc get build "$BUILD_NAME" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
        log_info "Build $BUILD_NAME status: ${BUILD_STATUS:-Unknown}"

        case "$BUILD_STATUS" in
            Complete)
                log_info "Build completed successfully"
                return 0
                ;;
            Failed|Error|Cancelled)
                log_error "Build failed with status: $BUILD_STATUS"
                oc logs "build/$BUILD_NAME" || true
                return 1
                ;;
            New|Pending|Running)
                sleep 5
                ;;
            *)
                log_warn "Unexpected build status '${BUILD_STATUS:-Unknown}' for $BUILD_NAME"
                sleep 5
                ;;
        esac

        ATTEMPT=$((ATTEMPT + 1))
    done

    log_error "Timed out waiting for build to complete"
    if [ -n "$BUILD_NAME" ]; then
        oc logs "build/$BUILD_NAME" || true
    fi
    return 1
}

verify_deployment() {
    log_step "Verifying deployment..."

    log_info "Checking pods..."
    oc get pods -n "$PROJECT_NAME"

    log_info ""
    log_info "Checking services..."
    oc get svc -n "$PROJECT_NAME"

    log_info ""
    log_info "Checking routes..."
    oc get route -n "$PROJECT_NAME"

    log_info ""
    log_info "Checking imagestreams..."
    oc get imagestream -n "$PROJECT_NAME"
}

print_access_info() {
    log_step "Deployment Summary"

    echo ""
    echo "=========================================="
    echo "  Docpipe Deployment Completed!"
    echo "=========================================="
    echo ""

    ROUTE_URL=$(oc get route docpipe-route -n "$PROJECT_NAME" -o jsonpath='{.spec.host}' 2>/dev/null || echo "Not configured")

    echo "Project: $PROJECT_NAME"
    echo "Application URL: https://$ROUTE_URL"
    echo ""

    echo "Useful Commands:"
    echo "  View pods:        oc get pods -n $PROJECT_NAME"
    echo "  View logs:        oc logs -f dc/docpipe-backend -n $PROJECT_NAME"
    echo "  View builds:      oc get builds -n $PROJECT_NAME"
    echo "  Start new build:  oc start-build docpipe-app -n $PROJECT_NAME"
    echo "  Scale app:        oc scale dc/docpipe-backend --replicas=3 -n $PROJECT_NAME"
    echo ""

    echo "Access the application:"
    echo "  curl -k https://$ROUTE_URL/health"
    echo ""
}

main() {
    echo ""
    echo "=========================================="
    echo "  Docpipe OpenShift Deployment"
    echo "=========================================="
    echo ""
    echo "Project Name: $PROJECT_NAME"
    echo "Git Repository: $GIT_REPO"
    echo "Git Branch: $GIT_BRANCH"
    echo ""

    check_prerequisites
    create_project
    create_git_secret
    create_imagestream
    create_app_from_git
    create_deployment

    log_info "Waiting for initial build to complete..."
    wait_for_build
    create_service
    create_route

    verify_deployment
    print_access_info

    log_info "Deployment script completed!"
}

# Run main function
main
