pipeline {

    agent any

    environment {

        AWS_REGION = 'ap-south-1'

        AWS_ACCOUNT_ID = credentials('376015725626')

        ECR_REPOSITORY = 'seclock'

        ECR_REGISTRY = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

        IMAGE_NAME = "${ECR_REGISTRY}/${ECR_REPOSITORY}"

        IMAGE_TAG = "${BUILD_NUMBER}"

        EKS_CLUSTER = 'my-cluster'

        K8S_NAMESPACE = 'seclock'

    }

    stages {

        stage('Checkout') {

            steps {

                checkout scm

            }

        }

        stage('Install Dependencies') {

            steps {

                sh '''
                    python3 -m venv .venv

                    . .venv/bin/activate

                    pip install --upgrade pip

                    pip install -r requirements.txt
                '''

            }

        }

        stage('Unit Tests') {

            steps {

                sh '''
                    . .venv/bin/activate

                    pytest -v
                '''

            }

        }

        stage('Static Code Analysis') {

            steps {

                sh '''
                    sonar-scanner \
                      -Dsonar.projectKey=seclock \
                      -Dsonar.sources=.
                '''

            }

        }

        stage('Trivy Filesystem Scan') {

            steps {

                sh '''
                    trivy fs \
                      --scanners vuln,secret \
                      --severity HIGH,CRITICAL \
                      .
                '''

            }

        }

        stage('Docker Build') {

            steps {

                sh '''
                    docker build \
                      -t ${IMAGE_NAME}:${IMAGE_TAG} .
                '''

            }

        }

        stage('Trivy Image Scan') {

            steps {

                sh '''
                    trivy image \
                      --severity HIGH,CRITICAL \
                      ${IMAGE_NAME}:${IMAGE_TAG}
                '''

            }

        }

        stage('Login to ECR') {

            steps {

                sh '''
                    aws ecr get-login-password \
                      --region ${AWS_REGION} \
                      | docker login \
                      --username AWS \
                      --password-stdin ${ECR_REGISTRY}
                '''

            }

        }

        stage('Push Image to ECR') {

            steps {

                sh '''
                    docker push ${IMAGE_NAME}:${IMAGE_TAG}
                '''

            }

        }

        stage('Deploy to EKS') {

            steps {

                sh '''
                    aws eks update-kubeconfig \
                      --region ${AWS_REGION} \
                      --name ${EKS_CLUSTER}

                    kubectl -n ${K8S_NAMESPACE} \
                      set image deployment/seclock \
                      seclock=${IMAGE_NAME}:${IMAGE_TAG}

                    kubectl -n ${K8S_NAMESPACE} \
                      rollout status deployment/seclock \
                      --timeout=180s
                '''

            }

        }

    }

    post {

        always {

            sh '''
                docker image prune -f || true
            '''

        }

        success {

            echo 'Pipeline completed successfully.'

        }

        failure {

            echo 'Pipeline failed. Check the logs.'

        }

    }

}
