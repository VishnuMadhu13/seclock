pipeline {
    agent any

    environment {
        AWS_REGION = 'ap-south-1'
        AWS_ACCOUNT_ID = credentials('aws-ecr-credentials')
        ECR_REPO_URI = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/seclock"
        IMAGE_TAG = "${env.BUILD_NUMBER}-${env.GIT_COMMIT.take(7)}"
        EKS_CLUSTER_NAME = 'seclock-cluster'
        K8S_NAMESPACE = 'seclock-prod'
    }

    stages {
        stage('1. Checkout & Secrets Scan') {
            steps {
                checkout scm
                sh 'docker run --rm -v ${WORKSPACE}:/path zricethezav/gitleaks:latest detect --source /path --redact -v || true'
            }
        }

        stage('2. SCA & SAST') {
            steps {
                sh '''
                    set -e

                    rm -rf venv
                    python3 -m venv venv

                    venv/bin/python -m pip install --upgrade pip
                    venv/bin/pip install -r requirements.txt
                    venv/bin/pip install pip-audit bandit

                    echo "Running dependency vulnerability scan..."
                    venv/bin/pip-audit

                    echo "Running Bandit security scan..."
                    venv/bin/bandit -r . \
                        -x ./venv,./test_e2e.py \
                        --severity-level medium \
                        --confidence-level high
                '''
            
        }

        stage('3. Unit & E2E Testing') {
            steps {
                sh '''#!/bin/bash
                    set -e

                    venv/bin/pip install pytest

                    venv/bin/pytest
                '''
            }
        }

        stage('4. Build Docker Image') {
            steps {
                script {
                    docker.build("${ECR_REPO_URI}:${IMAGE_TAG}", ".")
                }
            }
        }

        stage('5. Container Security Scan (Trivy)') {
            steps {
                // Mount the workspace (-v ${WORKSPACE}:/workspace) so Trivy can read .trivyignore
                sh """#!/bin/bash
                    docker run --rm \\
                        -v /var/run/docker.sock:/var/run/docker.sock \\
                        -v \${WORKSPACE}:/workspace \\
                        -w /workspace \\
                        aquasec/trivy image --exit-code 1 --ignorefile .trivyignore --severity CRITICAL \${ECR_REPO_URI}:\${IMAGE_TAG}
                """
            }
        }

        stage('6. AWS ECR Login & Push') {
            steps {
                script {
                    sh '''#!/bin/bash
                        aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
                    '''
                    docker.image("${ECR_REPO_URI}:${IMAGE_TAG}").push()
                    docker.image("${ECR_REPO_URI}:${IMAGE_TAG}").push("latest")
                }
            }
        }

        stage('7. Deploy to Amazon EKS') {
            steps {
                script {
                    sh """#!/bin/bash
                        aws eks update-kubeconfig --region ${AWS_REGION} --name ${EKS_CLUSTER_NAME}
                        sed -i 's|<AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/seclock:latest|${ECR_REPO_URI}:${IMAGE_TAG}|g' k8s/deployment.yaml
                        kubectl create namespace ${K8S_NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -
                        kubectl apply -f k8s/serviceaccount.yaml
                        kubectl apply -f k8s/deployment.yaml
                        kubectl apply -f k8s/service.yaml
                        kubectl rollout status deployment/seclock-deployment -n ${K8S_NAMESPACE} --timeout=120s
                    """
                }
            }
        }
    }

    post {
        always {
            echo 'Cleaning up workspace...'
            deleteDir()
        }
        failure {
            echo '🚨 Pipeline failed! Scroll up in the Console Output to find the actual error.'
        }
    }
}