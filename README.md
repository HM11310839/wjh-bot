# Bot-wjh

## 准备

1. 准备一个可用QQ号
2. 下载 [NapCat](https://napneko.github.io/) .
3. 下载 nb-cli
<br>(Cmd)`python -m pip install --user pipx`
<br>(Cmd)`python -m pipx ensurepath`
<br>(Cmd)`pipx install nb-cli`
4. 选择一个目录以启动 .

## NapCat - 设置方法
1. 下载NapCat Shell / App  [--url](https://napneko.github.io/guide/boot/Shell)
2. 添加一个Bot，输入QQ号，扫码登录
3. 添加 `WS反向Websocket客户端`
<br>URL：`ws://127.0.0.1:8080/onebot/v11/ws`
<br>记录显示的 TOKEN

## NB - 设置方法

1. 生成Project `nb create` .
2. 选择 `simple模版` `OneBot V11适配器` `FastAPI驱动器` `立即安装依赖与创建虚拟环境` .
3. 在 `src/plugins` 目录下编写插件py .
4. 更改 `.env`，写入`HOST=127.0.0.1 PORT=8080`
`ONEBOT_ACCESS_TOKEN=<刚才获取的TOKEN>` .
5. 使用 `nb run` 运行 .

## 附录

#`./something_else`目录下存放着解包及更新Up366的程序

## nonebot文档

See [Docs](https://nonebot.dev/)
