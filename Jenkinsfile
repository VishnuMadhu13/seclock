pipeline {
    agent any

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        AWS_REGION       = 'ap-south-1'
        ECR_REPO_URI     = '376015725626.dkr.ecr.ap-south-1.amazonaws.com/seclock'
        EKS_CLUSTER_NAME = 'seclock-cluster'
        K8S_NAMESPACE    = 'seclock-prod'
        AWS_CRED_ID      = 'aws-ecr-credentials'   // Jenkins credential ID (Username with password)
    }

    stages {

        stage('1. Checkout & Secrets Scan') {
            steps {
                checkout scm

                sh '''
                    set -e

                    docker run --rm \
                        -v "$WORKSPACE:/path" \
                        zricethezav/gitleaks:latest \
                        detect \
                        --source /path \
                        --redact \
                        -v
                '''
            }
        }

        stage('2. Set Image Tag') {
            steps {
                script {
                    def commit = sh(script: 'git rev-parse --short=7 HEAD', returnStdout: true).trim()
                    env.IMAGE = "${ECR_REPO_URI}:${env.BUILD_NUMBER}-${commit}"
                    echo "Image: ${env.IMAGE}"
                }
            }
        }

        stage('3. SCA & SAST') {
            steps {
                sh '''
                    set -e

                    rm -rf venv
                    python3 -m venv venv

                    venv/bin/python -m pip install --upgrade pip
                    venv/bin/pip install -r requirements.txt
                    venv/bin/pip install pip-audit bandit

                    # SCA: fail on known vulnerabilities in dependencies
                    venv/bin/pip-audit -r requirements.txt

                    # SAST: fail on medium+ severity findings (-ll), skip venv and tests
                    venv/bin/bandit -r . -ll -x ./venv,./test_e2e.py
                '''
            }
        }

        stage('4. Unit & E2E Testing') {
            steps {
                sh '''
                    set -e

                    venv/bin/pip install pytest httpx2
                    venv/bin/pytest -v
                '''
            }
        }

        stage('5. Build Docker Image') {
            steps {
                sh '''
                    set -e
                    test -n "$IMAGE" || { echo "IMAGE is empty"; exit 1; }
                    docker build --pull -t "$IMAGE" .
                '''
            }
        }

        stage('6. Container Security Scan (Trivy)') {
            options { timeout(time: 15, unit: 'MINUTES') }
            steps {
                // Download the vulnerability DB on its own, with retries
                retry(3) {
                    sh '''
                        set -e
                        mkdir -p "$JENKINS_HOME/.cache/trivy"

                        docker run --rm \
                        -v "$JENKINS_HOME/.cache/trivy":/root/.cache/ \
                        aquasec/trivy:latest image \
                        --download-db-only \
                        --no-progress \
                        --timeout 3m \
                        --db-repository public.ecr.aws/aquasecurity/trivy-db:2,ghcr.io/aquasecurity/trivy-db:2,mirror.gcr.io/aquasec/trivy-db:2
                    '''
                }

                // Scan using the cached DB only
                sh '''
                    set -e
                    test -n "$IMAGE" || { echo "IMAGE is empty"; exit 1; }

                    docker run --rm \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        -v "$JENKINS_HOME/.cache/trivy":/root/.cache/ \
                        aquasec/trivy:latest image \
                        --no-progress \
                        --scanners vuln \
                        --skip-db-update \
                        --exit-code 1 \
                        --severity CRITICAL \
                        "$IMAGE"
                '''
            }
        }

        stage('7. AWS ECR Login & Push') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: "${AWS_CRED_ID}",
                    usernameVariable: 'AWS_ACCESS_KEY_ID',
                    passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                )]) {
                    sh '''
                        set -e
                        export AWS_DEFAULT_REGION="$AWS_REGION"

                        ACCOUNT_ID=$(aws sts get-caller-identity \
                            --query Account \
                            --output text)
                        REGISTRY="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

                        aws ecr get-login-password --region "$AWS_REGION" | \
                            docker login --username AWS --password-stdin "$REGISTRY"

                        docker push "$IMAGE"

                        docker tag "$IMAGE" "$ECR_REPO_URI:latest"
                        docker push "$ECR_REPO_URI:latest"

                        docker logout "$REGISTRY"
                    '''
                }
            }
        }

        
        stage('8. Deploy to Amazon EKS') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: "${AWS_CRED_ID}",
                    usernameVariable: 'AWS_ACCESS_KEY_ID',
                    passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                )]) {
                    sh '''
                        set -e
                        export AWS_DEFAULT_REGION="$AWS_REGION"

                        aws eks update-kubeconfig \
                            --region "$AWS_REGION" \
                            --name "$EKS_CLUSTER_NAME"

                        # Replace the image placeholder in the manifest
                        sed -i "s|SEClock_IMAGE|$IMAGE|g" k8s/deployment.yaml

                        # Fail if the image line isn't what we expect
                        grep -qF "image: $IMAGE" k8s/deployment.yaml || {
                            echo "Image placeholder SEClock_IMAGE not found in k8s/deployment.yaml"
                            exit 1
                        }
                        grep -n "image:" k8s/deployment.yaml

                        kubectl create namespace "$K8S_NAMESPACE" \
                            --dry-run=client \
                            -o yaml | kubectl apply -f -

                        kubectl apply -f k8s/serviceaccount.yaml -n "$K8S_NAMESPACE"
                        kubectl apply -f k8s/deployment.yaml -n "$K8S_NAMESPACE"
                        kubectl apply -f k8s/service.yaml -n "$K8S_NAMESPACE"

                        kubectl rollout status \
                            deployment/seclock-deployment \
                            -n "$K8S_NAMESPACE" \
                            --timeout=120s
                    '''
                }
            }
        }
    }    
             

    post {
        always {
            echo 'Cleaning up workspace...'
            deleteDir()
        }

        success {
            echo '✅ Pipeline completed successfully!'
        }

        failure {
            echo '🚨 Pipeline failed! Check the console output.'
        }
    }
}