ARG IMAGE_REPOSITORY=quay.io/eduk8s

FROM ${IMAGE_REPOSITORY}/pkgs-java-tools:220301.042832.785fe13 AS java-tools

FROM ${IMAGE_REPOSITORY}/base-environment:220228.031741.790c79a

COPY --from=java-tools --chown=1001:0 /opt/jdk11 /opt/java

COPY --from=java-tools --chown=1001:0 /opt/gradle /opt/gradle

COPY --from=java-tools --chown=1001:0 /opt/maven /opt/maven

COPY --from=java-tools --chown=1001:0 /opt/code-server/extensions/.  /opt/code-server/extensions/

COPY --from=java-tools --chown=1001:0 /home/eduk8s/. /home/eduk8s/

COPY --from=java-tools --chown=1001:0 /opt/eduk8s/. /opt/eduk8s/

ENV PATH=/opt/java/bin:/opt/gradle/bin:/opt/maven/bin:$PATH \
    JAVA_HOME=/opt/java \
    M2_HOME=/opt/maven
