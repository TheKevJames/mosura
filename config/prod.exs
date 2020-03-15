use Mix.Config

config :mosura_server, port: String.to_integer(System.get_env("PORT") || "8080")
