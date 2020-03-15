defmodule Mosura.MixProject do
  use Mix.Project

  def project do
    [
      apps_path: "apps",
      version: "0.1.0",
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      releases: [
        server: [
          version: "0.1.0",
          applications: [mosura_server: :permanent]
        ]
      ]
    ]
  end

  defp deps do
    []
  end
end
