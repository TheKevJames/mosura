use config::{Config, ConfigError, Environment, File};
use serde::Deserialize;
use std::fs::OpenOptions;
use xdg::BaseDirectories;

fn generate_token() -> String {
    // TODO: actually do auth
    "xxx-fakeauth".to_string()
}

#[derive(Debug, Deserialize)]
pub struct Settings {
    pub api: String,
    #[serde(default = "generate_token")]
    pub token: String,
}

impl Settings {
    pub fn new() -> Result<Self, ConfigError> {
        let mut s = Config::new();
        s.set_default("api", "http://localhost:8080")?;

        let dirs = BaseDirectories::with_prefix("mosura").unwrap();
        let configfile = dirs
            .place_config_file("cli.yml")
            .expect("cannot create configuration directory");
        let _ = OpenOptions::new().create(true).write(true).open(&configfile);
        s.merge(File::from(configfile))?;

        s.merge(Environment::with_prefix("mosura"))?;

        // TODO: merge cli flags
        // https://github.com/mehcode/config-rs/issues/64

        s.try_into()
    }
}
