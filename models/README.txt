volis models. Nothing here is committed except this file; volis never downloads anything.

  vad\silero_vad.onnx     voice activity detector (as volis-rust)
  asr\<name>\             recognizers: a volis-rust folder with engine.toml, or a Hugging Face
                          download (.\fetch-model.ps1 <id> -Role asr)
  tts\<name>\             Piper voices with engine.toml (as volis-rust)
  tashkeel\libtashkeel_model.ort   optional: vowel marks for Arabic voices ([tts] diacritize)
  mt\<file>.gguf          the translator volis-rust also uses (exactly one at this level)
  mt\<name>\              further translators, one folder per model
                          (.\fetch-model.ps1 <id> -Role mt -Include "*Q4_K_M.gguf")

".\fetch-models.ps1" downloads every model listed in MODELS.md into place (-List shows what
it would fetch).

Run ".\.venv\Scripts\python.exe -m volis --report" to see what was found and why anything
isn't usable.
