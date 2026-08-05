"""THE 2-BOT LOOP: builder trains -> critic tests -> failures feed builder ->
retrain. Repeats until target accuracy or max rounds. All local, no Claude tokens.

Run: python tools/loop.py            (defaults: target 0.95, 6 rounds)
     python tools/loop.py 0.9 4
"""
import sys, json, os
from tools import common, builder, critic

def main():
    target = float(sys.argv[1]) if len(sys.argv) > 1 else 0.95
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    if os.path.exists(common.FAIL_PATH):
        os.remove(common.FAIL_PATH)          # fresh start

    best = 0.0
    for i in range(1, rounds + 1):
        print(f"\n===== ROUND {i} =====")
        builder.main()                        # learns from last round's failures
        acc = critic.main() or 0.0
        best = max(best, acc)
        if acc >= target:
            print(f"\n[loop] hit target {target:.0%} at round {i}. done.")
            break
    else:
        print(f"\n[loop] {rounds} rounds done. best accuracy {best:.2%}.")

if __name__ == "__main__":
    main()
