Volis's models. Nothing here is committed except this file; Volis never downloads anything.

  vad\silero_vad.onnx     the speech detector
  asr\<name>\             recognizers (.\fetch-model.ps1 <id> -Role asr)
  tts\<name>\             voices (.\fetch-model.ps1 <id> -Role tts)
  tashkeel\libtashkeel_model.ort   optional: vowel marks for Arabic voices ([tts] diacritize)
  mt\<file>.gguf          the default translator (at most one at this level)
  mt\<name>\              other translators, one folder per model
                          (.\fetch-model.ps1 <id> -Role mt -Include "*Q4_K_M.gguf")

".\fetch-models.ps1" downloads the models listed in MODELS.md into place (-List shows what it
would fetch).

Run ".\.venv\Scripts\python.exe -m volis --report" to see what was found and why anything
isn't usable.
