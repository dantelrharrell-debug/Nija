{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "buildCommand": "pip install -r requirements.txt",
    "dockerfilePath": "Dockerfile",
    "buildEnvironment": "V3"
  },
  "deploy": {
    "runtime": "V2",
    "numReplicas": 1,
    "startCommand": "python nija_preflight.py && python nija_startup.py",
    "sleepApplication": false,
    "useLegacyStacker": false,
    "multiRegionConfig": {
      "us-west2": {
        "numReplicas": 1
      }
    },
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  },
  "env": {
    "COINBASE_API_KEY_ID": "a9dae6d1-8592-4488-92cf-b3309a9ea5f2",
    "COINBASE_ORG_ID": "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0",
    "COINBASE_PEM_KEY_B64": "MHcCAQEEIOrZ/6/2ITZjLZAOYvnu7ZbAIQfDg8VEIP7XaqEAtZacoAoGCCqGSM49AwEHoUQDQgAELvgEIjI5gZyrhPOiZ4dZInphcm901xcHVAjdLmerldf/8agzuS1wOBJUqCeRF/wD/HuHs8fndWQACG7IUILRzw==",
    "LOG_LEVEL": "INFO"
  }
}
