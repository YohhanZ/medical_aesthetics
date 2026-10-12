FROM nginx:1.28.0-alpine
COPY frontend/customer/dist /usr/share/nginx/html
COPY frontend/admin/dist /usr/share/nginx/html/admin
COPY deploy/cloud-demo/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/cloud-demo/acme.conf /etc/nginx/acme.conf
