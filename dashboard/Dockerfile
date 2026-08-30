# The dashboard is a STATIC export (next.config.mjs sets output: "export"), so there is
# no Node process in the final image and no server-side rendering to keep alive. It is
# HTML and JS that the browser loads, which then talks to the gateway directly.
#
# That matters for where the gateway URL comes from. NEXT_PUBLIC_COMMONS_URL is baked in
# at BUILD time, and the browser making the calls is on the host, not in this container.
# So the correct value is the host's 127.0.0.1:8787, not a compose service name. Pointing
# it at http://gateway:8787 would resolve inside the network and be unreachable from the
# only place it is ever used.

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_COMMONS_URL=http://127.0.0.1:8787
ENV NEXT_PUBLIC_COMMONS_URL=$NEXT_PUBLIC_COMMONS_URL

# This Next version writes the static export INTO distDir, not into the `out/` directory
# the docs describe. Verified by building it: with distDir set, `out/` was never created
# and the HTML landed beside the chunks. Pinning distDir here means the COPY below has a
# known target instead of depending on which default won.
ENV NEXT_DIST_DIR=.next-docker

# `npm run build` guards against clobbering a running dev server by probing port 3300.
# In here nothing is listening, so it falls straight through.
RUN npm run build

# Fail the build loudly rather than shipping an empty web root. A dashboard that returns
# 404 for every page looks like a broken app; an image that refuses to build points at
# the one line that actually changed.
RUN test -f .next-docker/index.html


FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/.next-docker /usr/share/nginx/html

EXPOSE 3300

CMD ["nginx", "-g", "daemon off;"]
