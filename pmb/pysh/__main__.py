
from .lex import test, run
import sys

if sys.argv[1] == "test":
    test()
elif sys.argv[1] == "run":
    run(sys.argv[2])
