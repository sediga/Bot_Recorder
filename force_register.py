from playwright.__main__ import main
import sys

# Mimic CLI: `playwright install chromium`
sys.argv = ["playwright", "install", "chromium"]
main()
