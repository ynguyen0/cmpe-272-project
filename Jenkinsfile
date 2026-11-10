pipeline {
    agent any
    // Agent needs Python 3.12, uv 0.12.15, Chromium system dependencies,
    // and a dedicated PostgreSQL test database configured via environment.
    // GitHub Actions is the primary PR check; this runner uses the same check script.
    options { timestamps() }
    environment { DJANGO_SETTINGS_MODULE = 'config.settings.test' }
    stages {
        stage('Install') {
            steps {
                sh 'uv sync --locked'
                sh 'uv run --locked playwright install chromium'
            }
        }
        stage('Check') {
            steps {
                sh 'sh scripts/check.sh'
            }
        }
    }
}
