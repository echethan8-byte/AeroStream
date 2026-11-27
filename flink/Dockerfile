# Flink 1.18 + PyFlink + Kafka/JDBC connectors. Versions must stay aligned:
#   Flink 1.18.1  <->  apache-flink==1.18.1  <->  *-3.1.x-1.18 connector JARs
FROM flink:1.18.1-scala_2.12-java11

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-dev curl \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir apache-flink==1.18.1

ARG MVN=https://repo1.maven.org/maven2
RUN curl -fsSL -o /opt/flink/lib/flink-sql-connector-kafka-3.1.0-1.18.jar \
        ${MVN}/org/apache/flink/flink-sql-connector-kafka/3.1.0-1.18/flink-sql-connector-kafka-3.1.0-1.18.jar \
    && curl -fsSL -o /opt/flink/lib/flink-connector-jdbc-3.1.2-1.18.jar \
        ${MVN}/org/apache/flink/flink-connector-jdbc/3.1.2-1.18/flink-connector-jdbc-3.1.2-1.18.jar \
    && curl -fsSL -o /opt/flink/lib/postgresql-42.7.3.jar \
        ${MVN}/org/postgresql/postgresql/42.7.3/postgresql-42.7.3.jar

RUN mkdir -p /tmp/flink-checkpoints && chown flink:flink /tmp/flink-checkpoints

ENV PYTHONPATH=/opt/project
WORKDIR /opt/project
