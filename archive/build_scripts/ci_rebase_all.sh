Deployed via GitHub
Add ci_rebase_all.sh for automated branch rebasing This script stashes uncommitted changes, updates the main branch, and rebases all local branches onto the main branch, handling conflicts appropriately.
dantelrharrell-debug/Nija
main
Configuration

Pretty

Code
Save this in a file called railway.json to codify your deployments config.
Format


{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "RAILPACK",
    "buildCommand": "pip install -r requirements.txt",
    "buildEnvironment": "V3"
  },
  "deploy": {
    "runtime": "V2",
    "numReplicas": 1,
    "startCommand": "./start_all.sh",
    "sleepApplication": false,
    "useLegacyStacker": false,
    "multiRegionConfig": {
      "us-west2": {
        "numReplicas": 1
      }
    },
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
