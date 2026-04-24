# Shared image for the PyFlink CEP job — used by JobManager,
# TaskManager, and the one-shot submitter. The Flink base image is JRE
# only; we add a JDK (for pemja's setup.py to find headers), Python,
# pip deps (apache-flink + boto3 + kafka-python-ng + pytest), and the
# user code itself.
#
# Why one image for all three roles:
#   - JM coordinates Python jobs and benefits from having pyflink libs
#     locally for jar resolution.
#   - TM executes the user's Python operators in-process (pemja) so it
#     MUST have Python and apache-flink installed.
#   - Submitter runs `flink run --python` and needs the same pyflink
#     install to validate/serialize the job before submission.
#
# Entrypoint inheritance: we deliberately do NOT override Flink's
# /docker-entrypoint.sh — that script handles `jobmanager` and
# `taskmanager` commands. The submitter container in docker-compose.yml
# overrides ENTRYPOINT to /opt/flink-pyjob/submit.sh.
FROM flink:1.18.1-scala_2.12-java17

USER root

# JDK headers (pemja needs jni.h at JAVA_HOME/include — Flink base
# ships JRE only), Python, build tools for native extensions, and a
# `python` symlink (pyflink invokes plain `python`, not `python3`).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev python3-venv \
        openjdk-17-jdk build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(dpkg --print-architecture) \
    && ln -sfn "/usr/lib/jvm/java-17-openjdk-${ARCH}/include" /opt/java/openjdk/include \
    && ln -sfn /usr/bin/python3 /usr/local/bin/python

# ── Kafka connector JAR ──────────────────────────────────────────────────────
# PyFlink's `apache-flink` pip wheel ships only the Python wrappers — the
# Java connector classes (org.apache.flink.connector.kafka.*) are NOT
# bundled. Without this JAR, KafkaSource.builder() raises:
#   "Could not find the Java class 'org.apache.flink.connector.kafka.source.KafkaSource.builder'"
#
# We download the SHADED fat-jar (flink-sql-connector-kafka — confusingly
# named, but it works for DataStream API too and bundles kafka-clients,
# whereas the non-sql jar requires kafka-clients to be on the classpath
# separately). Version pin: 3.0.2-1.18 = connector 3.0.2 for Flink 1.18.x.
#
# Place in /opt/flink/lib/ so it's loaded by Flink's system classloader on
# JM, TM, and the submitter — all three need it for client-side validation
# and runtime execution.
ARG FLINK_KAFKA_CONNECTOR_VERSION=3.0.2-1.18
RUN curl -fsSL -o /opt/flink/lib/flink-sql-connector-kafka.jar \
        "https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/${FLINK_KAFKA_CONNECTOR_VERSION}/flink-sql-connector-kafka-${FLINK_KAFKA_CONNECTOR_VERSION}.jar"

WORKDIR /opt/flink-pyjob

COPY services/flink_pyjob/requirements.txt /opt/flink-pyjob/requirements.txt
RUN pip install --no-cache-dir -r /opt/flink-pyjob/requirements.txt

# Job code + shared platform modules. Keep this layer last so iteration
# on the job doesn't re-pull apache-flink (200MB) every rebuild.
COPY services/flink_pyjob /opt/flink-pyjob/services/flink_pyjob
COPY platform_shared    /opt/flink-pyjob/platform_shared

ENV PYTHONPATH=/opt/flink-pyjob

COPY services/flink_pyjob/submit.sh /opt/flink-pyjob/submit.sh
RUN chmod +x /opt/flink-pyjob/submit.sh
