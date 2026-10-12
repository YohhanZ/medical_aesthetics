FROM medical-consultation-sandbox:local
LABEL medical.consultation.worker="test-probe"
COPY sandbox/probe.py /probe.py
ENTRYPOINT ["python", "-I", "-u", "/probe.py"]
