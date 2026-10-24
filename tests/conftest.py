import os

# Tests generate boards on demand; the background 9x9 pool would make them
# nondeterministic and compete for CPU.
os.environ.setdefault('EXPERT_POOL', '0')
