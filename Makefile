.PHONY: demo analytics test clean

demo:
	python3 interactive.py

analytics:
	python3 dashboard.py

test:
	cd tests && python3 run.py

clean:
	rm -rf reports data __pycache__ tests/__pycache__ *.pyc
