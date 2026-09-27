# CMPE 272 Project

## Automatic build trigger

The `Jenkinsfile` uses Jenkins SCM polling (`pollSCM('H/5 * * * *')`).
Jenkins checks the configured Git branch every five minutes and starts the
pipeline when it detects new commits. `H` spreads polling across Jenkins jobs;
it does not mean a build runs every five minutes when nothing has changed.
No inbound webhook endpoint is required.

### Activate in Jenkins

1. Install the Jenkins Pipeline and Git plugins if they are not already installed.
2. Create or configure a Pipeline job with **Definition: Pipeline script from SCM**.
3. Select **Git**, set the repository URL to
   `https://github.com/ynguyen0/cmpe-272-project.git`, and select the branch to build.
   Add Jenkins credentials if repository access requires them.
4. Set **Script Path** to `Jenkinsfile` and save the job.
5. Commit and push these files to the configured branch, then run **Build Now**
   once so Jenkins loads the pipeline and registers the polling trigger.

### Verify the trigger

1. Push a new commit to the configured branch after the initial build completes.
2. Wait for the next polling cycle (approximately five minutes, plus any queue delay).
3. Check the job's **Git Polling Log** and confirm a new build starts with the
   cause **Started by an SCM change** in its console output.
4. Confirm the Build and Test stages finish. With no further commits, subsequent
   polls should report no changes and should not create another build.

The current stages demonstrate pipeline execution: Build lists workspace files
and Test prints a message. They do not yet compile an application or run a test suite.
Live trigger verification requires a configured Jenkins instance.

Reference: [Jenkins Pipeline triggers](https://www.jenkins.io/doc/book/pipeline/syntax/#triggers).
