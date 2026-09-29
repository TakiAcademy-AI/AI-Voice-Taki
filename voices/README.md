# voices/

Prepared reference voices live here, two files per voice:

    <name>.wav   a 5-9s clip of clean speech
    <name>.txt   the exact transcript of that clip

Create them with `python prepare_voice.py <recording> --name <name>`, then load
one with `VOICE=<name> ./start.sh`.

The `.wav` and `.txt` files are gitignored on purpose. A voice print is
biometric data — enough to make someone appear to say anything they never said.
Keep them local, and only clone voices you have permission to clone.
