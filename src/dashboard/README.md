# DLTS dashboard

A dashboard that support serving multiple DLTS backend.

## Configuration

DLTS dashboard is using [config](https://npmjs.com/package/config) to maintain configurations, read [Configuration Files](https://github.com/lorenwest/node-config/wiki/Configuration-Files) for more file-wise details.

The configuration schema (with description) is maintained in [config.schema.json](./server/api/validator/config.schema.json).

## Environment Variables

- `HOST` the host of server listening, default `::` (IPv6) or `0.0.0.0` (IPv4).
- `PORT` the port of server listening, default `3000`.
- `SSL_KEY` the SSL/TLS private key file for HTTPS / HTTP2 support.
- `SSL_CERT` the SSL/TLS certificate file for HTTPS / HTTP2 support.

## Local Development

1. Install [Node.js](https://nodejs.org/), version 10 is recommended.
2. Install [Yarn](https://yarnpkg.com/) for package maintaince.
3. Run `yarn` to install dependencies.
4. Prepare a [configuration](#configuration) file named `local.yaml` in `config` directory, it will be auto ignored by git.
5. For frontend development, run `yarn frontend`; for backend development, run `yarn build` and then `yarn backend`.
6. Open <http://localhost:3000/> (may be automatically opened by script) to preview.
7. For frontend development, local code changes will automatically refresh the browser; for backend development, local code changes will automatically restart the server.

## 关于访问 restapi 的问题

当前项目有关 job 的接口都会有 nodejs 去访问 restapi 服务，由于 restapi 有安全限制，如果开发时出现访问 restapi 服务 403 的情况，需要去服务器修改 restapi 的安全设置，增加自己的 ip白名单，如下：
```
location /apis {
  allow 本机 ip;
  ...other;
}
```