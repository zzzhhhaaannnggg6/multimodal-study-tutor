const {defineConfig} = require("@playwright/test");
module.exports = defineConfig({
  testDir: "tests/browser",
  workers: 1,
  use: {launchOptions: process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {}, trace:"retain-on-failure"},
  projects: [{name:"desktop",use:{viewport:{width:1280,height:800}}},{name:"mobile",use:{viewport:{width:390,height:844},isMobile:true,hasTouch:true}},{name:"narrow",use:{viewport:{width:320,height:740},isMobile:true,hasTouch:true}}]
});
