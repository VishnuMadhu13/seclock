pipeline {
    agent any

    environment {
        AWS_REGION = 'ap-south-1'
        ECR_REPO_URI = '376015725626.dkr.ecr.ap-south-1.amazonaws.com/seclock'
        EKS_CLUSTER_NAME = 'seclock-cluster'
        K8S_NAMESPACE = 'seclock-prod'
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
                    def shortCommit = sh(
                        script: 'git rev-parse --short=7 HEAD',
                        returnStdout: true
                    ).trim()

                    env.IMAGE_TAG = "${env.BUILD_NUMBER}-${shortCommit}"
                    env.FULL_IMAGE_URI = "${env.ECR_REPO_URI}:${env.IMAGE_TAG}"

                    echo "Image: ${env.FULL_IMAGE_URI}"
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

                '''
            }
        }

        stage('4. Unit & E2E Testing') {
            steps {
                sh '''
                    set -e

                    venv/bin/pip install pytest
                    venv/bin/pytest
                '''
            }
        }

        stage('5. Build Docker Image') {
            steps {
                script {
                    docker.build("${env.FULL_IMAGE_URI}", ".")
                }
            }
        }

        stage('6. Container Security Scan (Trivy)') {
            steps {
                sh '''
                    set -e

                    docker run --rm \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        -v "$WORKSPACE:/workspace" \
                        -w /workspace \
                        aquasec/trivy:latest \
                        image \
                        --exit-code 1 \
                        --severity CRITICAL \
                        "$FULL_IMAGE_URI"
                '''
            }
        }

        stage('7. AWS ECR Login & Push') {
            steps {
                sh '''
                    set -e

                    ACCOUNT_ID=$(aws sts get-caller-identity \
                        --query Account \
                        --output text)

                    aws ecr get-login-password \
                        --region "$AWS_REGION" | \
                        docker login \
                        --username AWS \
                        --password-stdin \
                        "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

                    docker push "$FULL_IMAGE_URI"

                    docker tag "$FULL_IMAGE_URI" "$ECR_REPO_URI:latest"
                    docker push "$ECR_REPO_URI:latest"
                '''
            }
        }

        stage('8. Deploy to Amazon EKS') {
            steps {
                sh '''
                    set -e

                    aws eks update-kubeconfig \
                        --region "$AWS_REGION" \
                        --name "$EKS_CLUSTER_NAME"

                    sed -i "s|<AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/seclock:latest|$FULL_IMAGE_URI|g" \
                        k8s/deployment.yaml

                    kubectl create namespace "$K8S_NAMESPACE" \
                        --dry-run=client \
                        -o yaml | kubectl apply -f -

                    kubectl apply -f k8s/serviceaccount.yaml \
                        -n "$K8S_NAMESPACE"

                    kubectl apply -f k8s/deployment.yaml \
                        -n "$K8S_NAMESPACE"

                    kubectl apply -f k8s/service.yaml \
                        -n "$K8S_NAMESPACE"

                    kubectl rollout status \
                        deployment/seclock-deployment \
                        -n "$K8S_NAMESPACE" \
                        --timeout=120s
                '''
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