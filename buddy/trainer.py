"""Train the intent model in-process (pure scikit-learn, seconds, offline).
Used for the automatic first-run training so users never touch a terminal.
"""
def train():
    from tools import builder
    builder.main()

def train_async(on_done=None):
    import threading
    def work():
        try:
            train()
        except Exception as e:
            print(f"[trainer] skipped: {e}")
        if on_done:
            on_done()
    threading.Thread(target=work, daemon=True).start()
