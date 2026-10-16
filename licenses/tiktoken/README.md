# Public tokenizer cache attribution

DeepSteam 2026.10.10-r3 carries six public OpenAI tokenizer assets so that
local token counting can initialize without downloading them on first use.
They are vocabulary/merge tables, not a cloud account, API credential or
language-model weights. No cache from another application was read or copied.

The source is the official `openai/tiktoken` 0.14.0 public encoding definition:
<https://github.com/openai/tiktoken/blob/0.14.0/tiktoken_ext/openai_public.py>.
Its MIT license, copyright 2022 OpenAI and Shantanu Jain, is retained verbatim
as `tiktoken-MIT-LICENSE.txt`.

| Public asset | Encoding use |
| --- | --- |
| `cl100k_base.tiktoken` | `cl100k_base` |
| `o200k_base.tiktoken` | `o200k_base`, `o200k_harmony` |
| `r50k_base.tiktoken` | `r50k_base` |
| `p50k_base.tiktoken` | `p50k_base`, `p50k_edit` |
| GPT-2 `vocab.bpe` | `gpt2` tokenizer |
| GPT-2 `encoder.json` | `gpt2` tokenizer |

`cache-manifest.json` preserves each full official public URL, the URL-derived
cache filename, byte length and official expected SHA-256. All six installed
asset hashes were independently checked against those expected values during
this notice collection. Runtime initialization and offline application
acceptance are separate checks performed by the installer team.

The original GPT-2 repository's modified MIT license is also retained as
`GPT-2-LICENSE.txt`, from commit
`9b63575ef42771a015060c964af2c3da4cf7c8ab`:
<https://github.com/openai/gpt-2/blob/9b63575ef42771a015060c964af2c3da4cf7c8ab/LICENSE>.
These two assets provide an encoding table; the package does not contain
GPT-2 model weights or present generated lessons as GPT-2 output.

Files are cached unchanged. Their presence does not enable an OpenAI paid API
or grant cloud-model credits. Switching to a cloud provider remains a separate
user configuration.
