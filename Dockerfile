FROM harbor.unext.jp/datascience-dev/ds-infra-kubebase:latest

WORKDIR /app/

# TODO Increment the number to force-refresh the lower layers.
RUN echo '8' > update_me && rm update_me

COPY pip.conf /etc/pip.conf
COPY requirements.txt /app

RUN pip install --no-cache-dir -r requirements.txt

# TODO Increment the number to force-refresh the lower layers.
RUN echo '3'

COPY *.py /app/
COPY bpr /app/bpr
COPY autoalts /app/autoalts
COPY config.yaml /app/

# RUN python  setup.py  sdist  bdist_wheel && pip install dist/*.whl

# Clean up
# RUN rm -r /app/target

# a way to communicate with airflow
ENTRYPOINT ["./entrypoint.sh"]