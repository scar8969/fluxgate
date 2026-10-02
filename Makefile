.PHONY: run test bench simulate bot clean

run:
	python run.py

test:
	python -m pytest tests/ -v

bench:
	python bench.py --requests 500 --concurrency 20

simulate:
	python simulate.py 24 30

bot:
	python bot.py

clean:
	rm -f fluxgate/fluxgate.db tg_links.json server.log
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
