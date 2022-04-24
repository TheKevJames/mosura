defmodule MosuraServer.MixProject do
  use Mix.Project

  def project do
    [
      app: :mosura_server,
      version: "0.1.0",
      build_path: "../../_build",
      config_path: "../../config/config.exs",
      deps_path: "../../deps",
      lockfile: "../../mix.lock",
      elixir: "~> 1.10",
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  def application do
    [
      extra_applications: [:httpoison, :logger, :plug_cowboy],
      mod: {MosuraServer, []}
    ]
  end

  defp deps do
    [
      {:httpoison, "== 1.8.1"},
      {:plug_cowboy, "== 2.5.2"},
      {:poison, "== 4.0.1"}
    ]
  end
end
