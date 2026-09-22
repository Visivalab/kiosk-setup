.PHONY: test run
export PYTHONPATH := pi/src

test:
	python3 -m unittest discover -s tests -v

run:
	python3 -m pi_kiosk
