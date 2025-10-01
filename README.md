# Testing Generative Engine LLMs using Deep Eval

This is a minimal example which uses Generative Engine as a LLM-as-judge with the [Deep Eval](https://deepeval.com/) library.

## Setup

- You will need [uv](https://docs.astral.sh/uv/) installed for python package management.
  You can install the required packages using `uv sync`.
- You need to setup some environment variables to use the [Generative Engine](https://generative.engine.capgemini.com/) for LLM requests. First, copy the example configuration file:

  ```sh
  cp .env.local .env
  ```

  Then replace the placeholder value for `API_KEY` with your own. If you don't already have one:

  1. Navigate to the Generative Engine
  2. Click on the avatar in the top-right
  3. Open the `API keys` dialog
  4. Create and copy the `General API Key`

  **Note:** Only add the API key to `.env` (listed in `.gitignore`) and **never commit it** to the Git repository.

- To run the test example, run the command
  `uv run test`. This runs the test script in the package which runs the command

  `uv run --env-file .env deepeval test run tests/test_example.py`.

## Custom Wrapper for DeepEval

To interface with the generative engine create a [custom LLM wrapper](https://deepeval.com/guides/guides-using-custom-llms) around the generative engine v2 API. This LLM is used to evaluate the LLM-as-judge metrics. The code is contained in the `gen_engine_deep_eval_wrapper.py` file.

We include an example test file using a [Hallucination test](https://deepeval.com/docs/metrics-hallucination).

We test the LLM application using an [End-to-end](https://deepeval.com/docs/evaluation-end-to-end-llm-evals) evaluation. The LLM application in our case is a simple LLM call using the Generative Engine wrapper and Langchain.

## SSL error when connecting to HuggingFace

If you are running the commands from the office, you may receive long error traces in the API console that end with:

```
  File ".venv\Lib\site-packages\huggingface_hub\utils\_http.py", line 93, in send
    return super().send(request, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File ".venv\Lib\site-packages\requests\adapters.py", line 698, in send
    raise SSLError(e, request=request)
requests.exceptions.SSLError: (MaxRetryError("HTTPSConnectionPool(host='huggingface.co', port=443): Max retries exceeded with url: /mixedbread-ai/mxbai-embed-large-v1/resolve/main/adapter_config.json (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1010)')))"), '(Request ID: 43d1f269-e3e7-4e3f-b9ab-548d08e29406)')
```

The API is attempting to download an embedded model from huggingface. The issue will typically only occur when on the XS4OFFICE network, due to ZScaler replacing certificates with its own.

The API uses the `certifi` Python package, which uses its own set of CAs rather than the system CAs. The solution is to add the Cap network root and intermediate certificates to those available in the `certifi` package. We don't need every CA from the Cap machine, just those relevant for accessing huggingface.

The solution on a Windows machine is:

1. In a browser, navigate to https://huggingface.co/
1. View the certificate and its certification hierarchy.
1. You should a hierarchy similar to: `CapgeminiPKIRootCA -> CapgeminiPKIIssuingCA2 -> global-internet.capgemini.com -> huggingface.co`
1. Select CapgeminiPKIIssuingCA2 (or whatever the lowest level CA is) and export as "Base64-encoded ASCII, **certificate chain**" with a `.crt` extension.
   - It needs both the CAs (selecting chain just saves needing to export both CAs manually), but it doesn’t need global-internet.capgemini.com.
1. Add the content of this file (viewable in a text editor) to the bottom of the CA certificates file used by certifi, at `.venv\Lib\site-packages\certifi\cacert.pem` in the tutorial directory.
1. Run the API command again. It should now be able to connect to huggingface.

## Agentic network remediation with Mininet

The `gen_engine_deep_eval.datacenter_agent` module wires the Generative Engine
LLM into a ReAct-style agent that can inspect and repair a Mininet
data-center topology.

### Prerequisites

- A Linux environment with [Mininet](https://github.com/mininet/mininet) installed
  and accessible to Python
- Root privileges (Mininet requires elevated permissions)
- Generative Engine credentials exported as `REST_API_BASE`, `API_KEY`, and
  optionally `GEN_ENGINE_MODEL`

### Demo workflow

```bash
sudo env REST_API_BASE=$REST_API_BASE API_KEY=$API_KEY \
  uv run python -m gen_engine_deep_eval.datacenter_agent
```

The demo boots a spine-leaf data-center topology (core, aggregation, and access
switches plus multi-rack hosts), intentionally drops a spine-to-aggregation
link, and lets the LLM reason through the provided tools:

- `get_topology_snapshot` to inspect blueprint metadata, switch models, and
  current link profiles
- `monitor_link` to observe utilisation, latency, and loss for any link
- `probe_connectivity` and `traceroute` to validate end-to-end reachability
- `simulate_failure` to inject fibre cuts, congestion, and latency spikes
- `activate_backup_path` and `restore_primary_path` to manage path
  reconfiguration

The agent should activate a backup path to maintain service while continuously
monitoring the affected link, and once the primary recovers, restore the
baseline configuration before reporting a `Final Answer` summary.
