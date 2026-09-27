pipeline {
    agent any
    triggers {
        // Check for new commits every five minutes; build only when SCM changes.
        pollSCM('H/5 * * * *')
    }
    stages {
        stage('Build') {
            steps {
                echo 'Building project'
                sh 'ls -lah'
            }
        }
        stage('Test') {
            steps {
                echo 'Running tests'
            }
        }
    }
}
