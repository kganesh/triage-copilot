# Runbook: Bad configuration or feature flag change

## When to use
Errors begin right after a configuration change or feature flag flip, without a code deploy. Typical signs are 401 or 403 responses from a provider, wrong endpoints, missing secrets, or invalid API keys.

## Diagnosis
Correlate the config change timestamp with the start of errors. Check whether the new endpoint or provider needs different credentials, and whether those secrets exist in the target environment.

## Steps
1. Revert the configuration change or flip the feature flag back to its previous value.
2. Verify error rate recovers within a few minutes of the revert.
3. Provision the correct credentials for the new endpoint in the secret store before retrying the change.
4. Require config changes that switch providers to go through a canary first.
